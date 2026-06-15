"""GoalRepo — the alignment tree (spec 01 Cluster D ``goal``)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Goal, GoalLevel
from chorus.ledger.repos._base import utcnow_iso


class GoalRepo:
    """Create + read ``goal`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, goal: Goal) -> Goal:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO goal (id, title, level, status, parent_id, owner_employee_id, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                goal.id,
                goal.title,
                goal.level.value,
                goal.status,
                goal.parent_id,
                goal.owner_employee_id,
                now,
                now,
            ),
        )
        self._conn.commit()
        return goal

    def get(self, goal_id: str) -> Goal | None:
        row = self._conn.execute("SELECT * FROM goal WHERE id = ?", (goal_id,)).fetchone()
        if row is None:
            return None
        return Goal(
            id=row["id"],
            title=row["title"],
            level=GoalLevel(row["level"]),
            status=row["status"],
            parent_id=row["parent_id"],
            owner_employee_id=row["owner_employee_id"],
        )
