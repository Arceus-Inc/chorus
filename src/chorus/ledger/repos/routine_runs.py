"""RoutineRunRepo — one firing → one task (spec 01 Cluster C ``routine_run``).

``record`` registers a firing; the partial-unique ``routine_run_idempotency_uq`` index makes dispatch
exact-once per non-null ``idempotency_key`` (a second firing with the same key raises
``IntegrityError``). ``dispatch`` links the spawned task and marks the run dispatched.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import RoutineRun, RoutineRunStatus
from chorus.ledger.repos._base import from_iso, utcnow_iso


class RoutineRunRepo:
    """Record, read, and dispatch ``routine_run`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, run: RoutineRun) -> RoutineRun:
        """Register a firing; the idempotency index rejects a duplicate keyed dispatch."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO routine_run (id, routine_id, trigger_id, status, dispatch_fingerprint, "
            "idempotency_key, linked_task_id, coalesced_into_run_id, routine_revision_id, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.routine_id,
                run.trigger_id,
                run.status.value,
                run.dispatch_fingerprint,
                run.idempotency_key,
                run.linked_task_id,
                run.coalesced_into_run_id,
                run.routine_revision_id,
                now,
            ),
        )
        self._conn.commit()
        recorded = self.get(run.id)
        assert recorded is not None  # just inserted in this transaction
        return recorded

    def get(self, run_id: str) -> RoutineRun | None:
        row = self._conn.execute(
            "SELECT * FROM routine_run WHERE id = ?", (run_id,)
        ).fetchone()
        return _row_to_run(row) if row is not None else None

    def by_routine(self, routine_id: str) -> list[RoutineRun]:
        """A routine's firings, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM routine_run WHERE routine_id = ? ORDER BY created_at, id",
            (routine_id,),
        ).fetchall()
        return [_row_to_run(row) for row in rows]

    def dispatch(self, run_id: str, *, linked_task_id: str) -> None:
        """Link the spawned task and mark the firing dispatched."""
        self._conn.execute(
            "UPDATE routine_run SET status = 'dispatched', linked_task_id = ? WHERE id = ?",
            (linked_task_id, run_id),
        )
        self._conn.commit()


def _row_to_run(row: sqlite3.Row) -> RoutineRun:
    return RoutineRun(
        id=row["id"],
        routine_id=row["routine_id"],
        trigger_id=row["trigger_id"],
        status=RoutineRunStatus(row["status"]),
        dispatch_fingerprint=row["dispatch_fingerprint"],
        idempotency_key=row["idempotency_key"],
        linked_task_id=row["linked_task_id"],
        coalesced_into_run_id=row["coalesced_into_run_id"],
        routine_revision_id=row["routine_revision_id"],
        created_at=from_iso(row["created_at"]),
    )
