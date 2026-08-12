"""Typed, per-run task carryover records."""

from __future__ import annotations

from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.ledger._errors import LedgerIntegrityError
from chorus.ledger._models import RunCarryover
from chorus.ledger.repos._base import LedgerConnection, LedgerRow, require_persisted, utcnow_iso


class RunCarryoverRepo:
    """Write the scheduler's landed context and derive task membership from its run."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def append(self, carryover: RunCarryover) -> RunCarryover:
        self._conn.execute(
            "INSERT INTO run_carryover (run_id, phase, recovery_hint, evaluator_notes, "
            "files_touched, todo_digest, summary, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (run_id) DO NOTHING",
            (
                carryover.run_id,
                carryover.phase.value,
                carryover.recovery_hint.value,
                list(carryover.evaluator_notes),
                list(carryover.files_touched),
                carryover.todo_digest,
                carryover.summary,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        stored = require_persisted(self.get(carryover.run_id), carryover.run_id)
        if stored != carryover:
            raise LedgerIntegrityError(
                f"run carryover {carryover.run_id!r} already exists with a different payload"
            )
        return stored

    def get(self, run_id: str) -> RunCarryover | None:
        row = self._conn.execute(
            "SELECT * FROM run_carryover WHERE run_id = ?", (run_id,)
        ).fetchone()
        return _row_to_carryover(row) if row is not None else None

    def for_task(self, task_id: str) -> list[RunCarryover]:
        rows = self._conn.execute(
            "SELECT carryover.* FROM run_carryover AS carryover "
            "JOIN run ON run.id = carryover.run_id "
            "WHERE run.task_id = ? ORDER BY run.created_at, run.id",
            (task_id,),
        ).fetchall()
        return [_row_to_carryover(row) for row in rows]


def _strings(value: object) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(item for item in value if isinstance(item, str))
    if isinstance(value, tuple):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _row_to_carryover(row: LedgerRow) -> RunCarryover:
    return RunCarryover(
        run_id=str(row["run_id"]),
        phase=LandedPhase(str(row["phase"])),
        recovery_hint=RecoveryHint(str(row["recovery_hint"])),
        evaluator_notes=_strings(row["evaluator_notes"]),
        files_touched=_strings(row["files_touched"]),
        todo_digest=str(row["todo_digest"]),
        summary=str(row["summary"]),
    )


__all__ = ["RunCarryoverRepo"]
