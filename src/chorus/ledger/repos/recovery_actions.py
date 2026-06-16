"""RecoveryActionRepo — liveness-as-visibility (spec 01 Cluster B ``recovery_action``, spec 02).

``open`` records an active recovery; the partial-unique indexes make it exact-once — at most one open
(active/escalated) recovery per source task, and one per ``(source, cause, fingerprint)`` — so a
second open raises ``IntegrityError``. ``escalate`` keeps it open; ``resolve`` closes it (freeing the
source); ``record_attempt`` bumps the bounded attempt counter.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import (
    RecoveryAction,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryStatus,
)
from chorus.ledger.repos._base import dumps, from_iso, loads, to_iso, utcnow_iso


class RecoveryActionRepo:
    """Open, escalate, attempt, and resolve ``recovery_action`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def open(self, action: RecoveryAction) -> RecoveryAction:
        """Record an active recovery; the exact-once indexes reject a second open per source."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO recovery_action (id, source_task_id, recovery_task_id, kind, status, "
            "owner_employee_id, owner_user_id, previous_owner_employee_id, "
            "return_owner_employee_id, cause, fingerprint, evidence, next_action, wake_policy, "
            "monitor_policy, attempt_count, max_attempts, timeout_at, last_attempt_at, "
            "resolved_at, outcome, resolution_note, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, "
            "NULL, ?)",
            (
                action.id,
                action.source_task_id,
                action.recovery_task_id,
                action.kind.value,
                RecoveryStatus.ACTIVE.value,
                action.owner_employee_id,
                action.owner_user_id,
                action.previous_owner_employee_id,
                action.return_owner_employee_id,
                action.cause,
                action.fingerprint,
                dumps(action.evidence),
                action.next_action,
                dumps(action.wake_policy),
                dumps(action.monitor_policy),
                action.attempt_count,
                action.max_attempts,
                to_iso(action.timeout_at),
                now,
            ),
        )
        self._conn.commit()
        opened = self.get(action.id)
        assert opened is not None  # just inserted in this transaction
        return opened

    def get(self, action_id: str) -> RecoveryAction | None:
        row = self._conn.execute(
            "SELECT * FROM recovery_action WHERE id = ?", (action_id,)
        ).fetchone()
        return _row_to_action(row) if row is not None else None

    def active_for_source(self, source_task_id: str) -> RecoveryAction | None:
        """The open (active/escalated) recovery for a source task, or ``None``."""
        row = self._conn.execute(
            "SELECT * FROM recovery_action WHERE source_task_id = ? "
            "AND status IN ('active', 'escalated')",
            (source_task_id,),
        ).fetchone()
        return _row_to_action(row) if row is not None else None

    def all_open(self) -> list[RecoveryAction]:
        """Every open (active/escalated) recovery, oldest first - the sweep's fold candidates."""
        rows = self._conn.execute(
            "SELECT * FROM recovery_action WHERE status IN ('active', 'escalated') "
            "ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_action(row) for row in rows]

    def escalate(self, action_id: str) -> None:
        self._conn.execute(
            "UPDATE recovery_action SET status = 'escalated' WHERE id = ? AND status = 'active'",
            (action_id,),
        )
        self._conn.commit()

    def record_attempt(self, action_id: str) -> RecoveryAction:
        """Increment the bounded attempt counter and stamp the attempt time.

        Refuses to exceed ``max_attempts`` — retries stop once the cap is reached.
        """
        action = self.get(action_id)
        if action is None:
            raise KeyError(action_id)
        if action.attempt_count >= action.max_attempts:
            raise ValueError(
                f"recovery {action_id} exhausted its {action.max_attempts} attempt(s)"
            )
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE recovery_action SET attempt_count = attempt_count + 1, last_attempt_at = ? "
            "WHERE id = ?",
            (now, action_id),
        )
        self._conn.commit()
        updated = self.get(action_id)
        assert updated is not None  # exists — we read it above
        return updated

    def resolve(
        self,
        action_id: str,
        *,
        outcome: RecoveryOutcome,
        resolution_note: str | None = None,
    ) -> None:
        """Close the recovery (owner acted), freeing the source for a future one."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE recovery_action SET status = 'resolved', outcome = ?, resolution_note = ?, "
            "resolved_at = ? WHERE id = ? AND status IN ('active', 'escalated')",
            (outcome.value, resolution_note, now, action_id),
        )
        self._conn.commit()

    def fold(self, action_id: str, *, resolution_note: str | None = None) -> None:
        """Fold the recovery as a *false positive* — the source resolved itself (spec 02 §6).

        Distinct terminal state from :meth:`resolve` (owner acted): a fold means the alert was moot,
        not that anyone did the work. Both free the source (neither is in the open index set).
        """
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE recovery_action SET status = 'folded', outcome = ?, resolution_note = ?, "
            "resolved_at = ? WHERE id = ? AND status IN ('active', 'escalated')",
            (RecoveryOutcome.FALSE_POSITIVE.value, resolution_note, now, action_id),
        )
        self._conn.commit()


def _row_to_action(row: sqlite3.Row) -> RecoveryAction:
    raw_outcome = row["outcome"]
    return RecoveryAction(
        id=row["id"],
        source_task_id=row["source_task_id"],
        kind=RecoveryKind(row["kind"]),
        recovery_task_id=row["recovery_task_id"],
        status=RecoveryStatus(row["status"]),
        owner_employee_id=row["owner_employee_id"],
        owner_user_id=row["owner_user_id"],
        previous_owner_employee_id=row["previous_owner_employee_id"],
        return_owner_employee_id=row["return_owner_employee_id"],
        cause=row["cause"],
        fingerprint=row["fingerprint"],
        evidence=loads(row["evidence"]) or {},
        next_action=row["next_action"],
        wake_policy=loads(row["wake_policy"]) or {},
        monitor_policy=loads(row["monitor_policy"]) or {},
        attempt_count=row["attempt_count"],
        max_attempts=row["max_attempts"],
        timeout_at=from_iso(row["timeout_at"]),
        last_attempt_at=from_iso(row["last_attempt_at"]),
        resolved_at=from_iso(row["resolved_at"]),
        outcome=RecoveryOutcome(raw_outcome) if raw_outcome is not None else None,
        resolution_note=row["resolution_note"],
        created_at=from_iso(row["created_at"]),
    )
