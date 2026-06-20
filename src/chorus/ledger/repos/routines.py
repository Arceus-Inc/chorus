"""RoutineRepo — cron templates (spec 01 Cluster C ``routine``)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import (
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRevision,
    RoutineStatus,
    RoutineTarget,
)
from chorus.ledger.repos._base import dumps, loads, utcnow_iso


class RoutineRepo:
    """Create + read ``routine`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, routine: Routine) -> Routine:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO routine (id, employee_id, goal_id, parent_task_id, intent_template, "
            "target, concurrency_policy, catch_up_policy, status, env, routine_key, "
            "latest_revision_id, latest_revision_no, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                dumps(routine.env) if routine.env is not None else None,
                routine.routine_key,
                routine.latest_revision_id,
                routine.latest_revision_no,
                now,
                now,
            ),
        )
        self._conn.commit()
        created = self.get(routine.id)
        assert created is not None  # just inserted in this transaction
        return created

    def set_head(self, routine_id: str, revision: RoutineRevision) -> None:
        """Make ``revision`` the live head (spec 13 §2.2): advance the pointer **and** mirror the
        revision's definition onto the routine row, so the row always reflects the current
        definition while ``routine_revision`` keeps the immutable history. One atomic write."""
        self._conn.execute(
            "UPDATE routine SET intent_template = ?, target = ?, concurrency_policy = ?, "
            "catch_up_policy = ?, env = ?, latest_revision_id = ?, latest_revision_no = ?, "
            "updated_at = ? WHERE id = ?",
            (
                revision.intent_template,
                revision.target.value,
                revision.concurrency_policy.value,
                revision.catch_up_policy.value,
                dumps(revision.env) if revision.env is not None else None,
                revision.id,
                revision.revision_no,
                utcnow_iso(),
                routine_id,
            ),
        )
        self._conn.commit()

    def get(self, routine_id: str) -> Routine | None:
        row = self._conn.execute("SELECT * FROM routine WHERE id = ?", (routine_id,)).fetchone()
        return _row_to_routine(row) if row is not None else None

    def list_active(self) -> list[Routine]:
        """All active routines, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM routine WHERE status = 'active' ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_routine(row) for row in rows]

    def list(self, *, employee_id: str | None = None) -> list[Routine]:
        """All routines (any status), oldest first; scoped to one employee when given."""
        if employee_id is None:
            rows = self._conn.execute("SELECT * FROM routine ORDER BY created_at, id").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM routine WHERE employee_id = ? ORDER BY created_at, id",
                (employee_id,),
            ).fetchall()
        return [_row_to_routine(row) for row in rows]

    def set_status(self, routine_id: str, status: RoutineStatus) -> None:
        """Pause or resume a routine — the only mutable field on a routine row (spec 13 §3.2)."""
        self._conn.execute(
            "UPDATE routine SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, utcnow_iso(), routine_id),
        )
        self._conn.commit()


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
        env=loads(row["env"]),
        routine_key=row["routine_key"],
        latest_revision_id=row["latest_revision_id"],
        latest_revision_no=row["latest_revision_no"],
    )
