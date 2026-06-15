"""DependencyRepo — the work DAG edges (spec 01 Cluster A ``task_dependency``, spec 02/03).

An edge ``(task_id, depends_on_id)`` means *task_id depends on / is blocked by depends_on_id*. The
repo keeps the DAG acyclic (self-edges and cycles rejected) and answers the resolution queries the
scheduler needs: a task's unresolved blockers, and the dependents a just-finished task unblocks.
A ``cancelled`` blocker does **not** count as resolved (spec 02 §2) — only ``done`` does.
"""

from __future__ import annotations

import sqlite3
import uuid

from chorus.errors import ChorusError
from chorus.ledger._models import TaskDependency
from chorus.ledger.repos._base import from_iso, utcnow_iso


class DependencyCycleError(ChorusError):
    """Adding an edge would create a self-loop or a cycle in the work DAG (spec 02 §2)."""


class DependencyRepo:
    """Create/read/remove ``task_dependency`` edges + the blocker-resolution queries."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def add(self, task_id: str, depends_on_id: str) -> TaskDependency:
        """Add "task_id depends on depends_on_id" (idempotent). Rejects self-edges and cycles."""
        if task_id == depends_on_id:
            raise DependencyCycleError(f"task {task_id!r} cannot depend on itself")
        if self._reaches(depends_on_id, task_id):
            raise DependencyCycleError(
                f"{task_id!r} depends on {depends_on_id!r} would create a cycle"
            )
        now = utcnow_iso()
        edge_id = f"dep_{uuid.uuid4().hex[:12]}"
        self._conn.execute(
            "INSERT INTO task_dependency (id, task_id, depends_on_id, created_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT (task_id, depends_on_id) DO NOTHING",
            (edge_id, task_id, depends_on_id, now),
        )
        self._conn.commit()
        return TaskDependency(
            id=edge_id, task_id=task_id, depends_on_id=depends_on_id, created_at=from_iso(now)
        )

    def remove(self, task_id: str, depends_on_id: str) -> None:
        self._conn.execute(
            "DELETE FROM task_dependency WHERE task_id = ? AND depends_on_id = ?",
            (task_id, depends_on_id),
        )
        self._conn.commit()

    def blockers(self, task_id: str) -> list[str]:
        """Ids of the tasks ``task_id`` depends on (in insertion order)."""
        rows = self._conn.execute(
            "SELECT depends_on_id FROM task_dependency WHERE task_id = ? ORDER BY created_at, id",
            (task_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def dependents(self, depends_on_id: str) -> list[str]:
        """Ids of the tasks that depend on ``depends_on_id`` (in insertion order)."""
        rows = self._conn.execute(
            "SELECT task_id FROM task_dependency WHERE depends_on_id = ? ORDER BY created_at, id",
            (depends_on_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def unresolved_blockers(self, task_id: str) -> list[str]:
        """Blockers of ``task_id`` not yet ``done`` (``cancelled`` is not resolved)."""
        rows = self._conn.execute(
            "SELECT d.depends_on_id FROM task_dependency d "
            "JOIN task b ON b.id = d.depends_on_id "
            "WHERE d.task_id = ? AND b.status <> 'done' ORDER BY d.created_at, d.id",
            (task_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def newly_unblocked_dependents(self, done_task_id: str) -> list[str]:
        """Dependents of ``done_task_id`` whose blockers are now *all* ``done`` (resolution wakes)."""
        rows = self._conn.execute(
            "SELECT d.task_id FROM task_dependency d "
            "WHERE d.depends_on_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM task_dependency d2 JOIN task b ON b.id = d2.depends_on_id "
            "  WHERE d2.task_id = d.task_id AND b.status <> 'done'"
            ") ORDER BY d.created_at, d.id",
            (done_task_id,),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def _reaches(self, start: str, target: str) -> bool:
        """True if ``target`` is reachable from ``start`` along blocker edges (cycle check)."""
        seen: set[str] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            for blocker in self.blockers(node):
                if blocker == target:
                    return True
                if blocker not in seen:
                    seen.add(blocker)
                    stack.append(blocker)
        return False
