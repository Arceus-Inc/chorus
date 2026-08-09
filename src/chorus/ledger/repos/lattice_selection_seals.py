"""Durable outbox for exact Lattice selection seals."""

from __future__ import annotations

from datetime import UTC, datetime

from dream.contracts.strategy import LandedPhase

from chorus.ledger._models import LatticeSelectionSeal
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
)


class LatticeSelectionSealConflictError(RuntimeError):
    """One beat run was replayed with a different employee, phase, or landing time."""


class LatticeSelectionSealRepo:
    """Enqueue, claim, retry, and terminally resolve durable Lattice seal commands."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def enqueue(self, seal: LatticeSelectionSeal) -> LatticeSelectionSeal:
        """Persist an immutable seal command; exact replay is idempotent."""
        next_attempt_at = seal.next_attempt_at or seal.landed_at
        created_at = seal.created_at or datetime.now(UTC)
        self._conn.execute(
            "INSERT INTO lattice_selection_seal_outbox "
            "(beat_run_id, employee_id, outcome_phase, landed_at, attempt_count, "
            "next_attempt_at, last_error, sealed_at, terminal_at, created_at) "
            "VALUES (?, ?, ?, ?, 0, ?, NULL, NULL, NULL, ?) "
            "ON CONFLICT (company_id, beat_run_id) DO NOTHING",
            (
                seal.beat_run_id,
                seal.employee_id,
                seal.outcome_phase.value,
                to_iso(seal.landed_at),
                to_iso(next_attempt_at),
                to_iso(created_at),
            ),
        )
        self._conn.commit()
        persisted = require_persisted(self.get(seal.beat_run_id), seal.beat_run_id)
        if _identity(persisted) == _identity(seal):
            return persisted
        error = (
            "immutable Lattice selection seal conflict for run "
            f"{seal.beat_run_id}: persisted={_identity(persisted)!r} replay={_identity(seal)!r}"
        )
        raise LatticeSelectionSealConflictError(error)

    def claim_one(
        self,
        beat_run_id: str,
        *,
        now: datetime,
        lease_until: datetime,
    ) -> LatticeSelectionSeal | None:
        """Claim one due command by moving its next due time to a crash-recovery lease."""
        row = self._conn.execute(
            "UPDATE lattice_selection_seal_outbox "
            "SET attempt_count = attempt_count + 1, next_attempt_at = ? "
            "WHERE beat_run_id = ? AND sealed_at IS NULL AND terminal_at IS NULL "
            "AND next_attempt_at <= ? RETURNING *",
            (to_iso(lease_until), beat_run_id, to_iso(now)),
        ).fetchone()
        self._conn.commit()
        return _row_to_seal(row) if row is not None else None

    def claim_due(
        self,
        *,
        now: datetime,
        lease_until: datetime,
        limit: int,
    ) -> tuple[LatticeSelectionSeal, ...]:
        """Claim a bounded due batch with SKIP LOCKED across concurrent schedulers."""
        if limit <= 0:
            return ()
        rows = self._conn.execute(
            "WITH due AS ("
            "  SELECT company_id, beat_run_id FROM lattice_selection_seal_outbox "
            "  WHERE sealed_at IS NULL AND terminal_at IS NULL AND next_attempt_at <= ? "
            "  ORDER BY next_attempt_at, beat_run_id FOR UPDATE SKIP LOCKED LIMIT ?"
            ") UPDATE lattice_selection_seal_outbox AS seal "
            "SET attempt_count = seal.attempt_count + 1, next_attempt_at = ? "
            "FROM due WHERE seal.company_id = due.company_id "
            "AND seal.beat_run_id = due.beat_run_id RETURNING seal.*",
            (to_iso(now), limit, to_iso(lease_until)),
        ).fetchall()
        self._conn.commit()
        return tuple(sorted((_row_to_seal(row) for row in rows), key=_due_order))

    def mark_retry(
        self,
        seal: LatticeSelectionSeal,
        *,
        error: str,
        next_attempt_at: datetime,
    ) -> LatticeSelectionSeal:
        """Release one claimed transient failure onto its bounded-backoff due time."""
        cursor = self._conn.execute(
            "UPDATE lattice_selection_seal_outbox SET next_attempt_at = ?, last_error = ? "
            "WHERE beat_run_id = ? AND employee_id = ? AND outcome_phase = ? AND landed_at = ? "
            "AND attempt_count = ? AND next_attempt_at = ? "
            "AND sealed_at IS NULL AND terminal_at IS NULL",
            (
                to_iso(next_attempt_at),
                error,
                seal.beat_run_id,
                seal.employee_id,
                seal.outcome_phase.value,
                to_iso(seal.landed_at),
                seal.attempt_count,
                to_iso(seal.next_attempt_at),
            ),
        )
        self._conn.commit()
        return self._after_claim_cas(seal, affected=cursor.rowcount, operation="retry")

    def mark_sealed(
        self,
        seal: LatticeSelectionSeal,
        *,
        sealed_at: datetime,
    ) -> LatticeSelectionSeal:
        """Acknowledge an exact Lattice seal; exact replay after a mark failure converges here."""
        cursor = self._conn.execute(
            "UPDATE lattice_selection_seal_outbox "
            "SET sealed_at = ?, next_attempt_at = NULL, last_error = NULL "
            "WHERE beat_run_id = ? AND employee_id = ? AND outcome_phase = ? AND landed_at = ? "
            "AND attempt_count = ? AND next_attempt_at = ? "
            "AND sealed_at IS NULL AND terminal_at IS NULL",
            (
                to_iso(sealed_at),
                seal.beat_run_id,
                seal.employee_id,
                seal.outcome_phase.value,
                to_iso(seal.landed_at),
                seal.attempt_count,
                to_iso(seal.next_attempt_at),
            ),
        )
        self._conn.commit()
        persisted = self._after_claim_cas(seal, affected=cursor.rowcount, operation="seal")
        if cursor.rowcount == 1 and persisted.sealed_at is None:
            raise LatticeSelectionSealConflictError(
                f"Lattice selection seal {seal.beat_run_id} was not acknowledged"
            )
        return persisted

    def mark_terminal(
        self,
        seal: LatticeSelectionSeal,
        *,
        error: str,
        terminal_at: datetime,
    ) -> LatticeSelectionSeal:
        """Stop retrying a deterministic conflict while retaining an observable durable error."""
        cursor = self._conn.execute(
            "UPDATE lattice_selection_seal_outbox "
            "SET terminal_at = ?, next_attempt_at = NULL, last_error = ? "
            "WHERE beat_run_id = ? AND employee_id = ? AND outcome_phase = ? AND landed_at = ? "
            "AND attempt_count = ? AND next_attempt_at = ? "
            "AND sealed_at IS NULL AND terminal_at IS NULL",
            (
                to_iso(terminal_at),
                error,
                seal.beat_run_id,
                seal.employee_id,
                seal.outcome_phase.value,
                to_iso(seal.landed_at),
                seal.attempt_count,
                to_iso(seal.next_attempt_at),
            ),
        )
        self._conn.commit()
        return self._after_claim_cas(seal, affected=cursor.rowcount, operation="terminate")

    def get(self, beat_run_id: str) -> LatticeSelectionSeal | None:
        row = self._conn.execute(
            "SELECT * FROM lattice_selection_seal_outbox WHERE beat_run_id = ?",
            (beat_run_id,),
        ).fetchone()
        return _row_to_seal(row) if row is not None else None

    def _require_exact(self, seal: LatticeSelectionSeal) -> LatticeSelectionSeal:
        persisted = require_persisted(self.get(seal.beat_run_id), seal.beat_run_id)
        if _identity(persisted) != _identity(seal):
            raise LatticeSelectionSealConflictError(
                f"immutable Lattice selection seal conflict for run {seal.beat_run_id}"
            )
        return persisted

    def _after_claim_cas(
        self,
        seal: LatticeSelectionSeal,
        *,
        affected: int,
        operation: str,
    ) -> LatticeSelectionSeal:
        """Accept this claim's write or a state that proves a newer worker already advanced it."""
        persisted = self._require_exact(seal)
        if affected == 1:
            return persisted
        superseded = (
            persisted.sealed_at is not None
            or persisted.terminal_at is not None
            or persisted.attempt_count > seal.attempt_count
            or persisted.next_attempt_at != seal.next_attempt_at
        )
        if affected == 0 and superseded:
            return persisted
        raise LatticeSelectionSealConflictError(
            f"Lattice selection seal {seal.beat_run_id} could not {operation} its exact claim"
        )


def _identity(seal: LatticeSelectionSeal) -> tuple[str, str, LandedPhase, datetime]:
    return seal.employee_id, seal.beat_run_id, seal.outcome_phase, seal.landed_at


def _due_order(seal: LatticeSelectionSeal) -> tuple[datetime, str]:
    return seal.next_attempt_at or seal.landed_at, seal.beat_run_id


def _row_to_seal(row: LedgerRow) -> LatticeSelectionSeal:
    return LatticeSelectionSeal(
        employee_id=row["employee_id"],
        beat_run_id=row["beat_run_id"],
        outcome_phase=LandedPhase(row["outcome_phase"]),
        landed_at=_required_time(row["landed_at"], "landed_at"),
        attempt_count=row["attempt_count"],
        next_attempt_at=from_iso(row["next_attempt_at"]),
        last_error=row["last_error"],
        sealed_at=from_iso(row["sealed_at"]),
        terminal_at=from_iso(row["terminal_at"]),
        created_at=from_iso(row["created_at"]),
    )


def _required_time(value: str | None, field: str) -> datetime:
    parsed = from_iso(value)
    if parsed is None:
        raise ValueError(f"Lattice selection seal {field} is required")
    return parsed


__all__ = [
    "LatticeSelectionSealConflictError",
    "LatticeSelectionSealRepo",
]
