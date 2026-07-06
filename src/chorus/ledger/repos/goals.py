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
        return self._row_to_goal(row)

    def children(self, parent_id: str | None) -> list[Goal]:
        """Direct children of ``parent_id`` — the roots when ``parent_id`` is ``None`` (spec: the tree)."""
        if parent_id is None:
            rows = self._conn.execute(
                "SELECT * FROM goal WHERE parent_id IS NULL ORDER BY created_at"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM goal WHERE parent_id = ? ORDER BY created_at", (parent_id,)
            ).fetchall()
        return [self._row_to_goal(row) for row in rows]

    def update(self, goal: Goal) -> Goal:
        """Update a goal's mutable fields (title / level / status / parent / owner)."""
        self._conn.execute(
            "UPDATE goal SET title = ?, level = ?, status = ?, parent_id = ?, "
            "owner_employee_id = ?, updated_at = ? WHERE id = ?",
            (
                goal.title,
                goal.level.value,
                goal.status,
                goal.parent_id,
                goal.owner_employee_id,
                utcnow_iso(),
                goal.id,
            ),
        )
        self._conn.commit()
        return goal

    @staticmethod
    def _row_to_goal(row: sqlite3.Row) -> Goal:
        return Goal(
            id=row["id"],
            title=row["title"],
            level=GoalLevel(row["level"]),
            status=row["status"],
            parent_id=row["parent_id"],
            owner_employee_id=row["owner_employee_id"],
        )
