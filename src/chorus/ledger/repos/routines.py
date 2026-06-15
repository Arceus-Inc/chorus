"""RoutineRepo — cron templates (spec 01 Cluster C ``routine``)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import (
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineStatus,
    RoutineTarget,
)
from chorus.ledger.repos._base import utcnow_iso


class RoutineRepo:
    """Create + read ``routine`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, routine: Routine) -> Routine:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO routine (id, employee_id, goal_id, parent_task_id, intent_template, "
            "target, concurrency_policy, catch_up_policy, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                routine.id,
                routine.employee_id,
                routine.goal_id,
                routine.parent_task_id,
                routine.intent_template,
                routine.target.value,
                routine.concurrency_policy.value,
                routine.catch_up_policy.value,
                routine.status.value,
                now,
                now,
            ),
        )
        self._conn.commit()
        created = self.get(routine.id)
        assert created is not None  # just inserted in this transaction
        return created

    def get(self, routine_id: str) -> Routine | None:
        row = self._conn.execute("SELECT * FROM routine WHERE id = ?", (routine_id,)).fetchone()
        return _row_to_routine(row) if row is not None else None

    def list_active(self) -> list[Routine]:
        """All active routines, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM routine WHERE status = 'active' ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_routine(row) for row in rows]


def _row_to_routine(row: sqlite3.Row) -> Routine:
    return Routine(
        id=row["id"],
        employee_id=row["employee_id"],
        intent_template=row["intent_template"],
        goal_id=row["goal_id"],
        parent_task_id=row["parent_task_id"],
        target=RoutineTarget(row["target"]),
        concurrency_policy=RoutineConcurrency(row["concurrency_policy"]),
        catch_up_policy=RoutineCatchUp(row["catch_up_policy"]),
        status=RoutineStatus(row["status"]),
    )
