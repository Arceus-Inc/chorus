"""TaskRepo — the load-bearing aggregate (spec 01 Cluster A, spec 03).

Owns the durable work-unit operations the scheduler depends on: exact-once ``submit`` (the origin
partial-unique indexes reject a duplicate self-spawned task), the **atomic checkout CAS**
(``UPDATE … WHERE checkout_run_id IS NULL`` — a 0-row result is a 409, never a clobber),
terminal-only ``release_locks``, and dependency-free ``list_eligible`` (M1; the dependency gate
arrives with the M2 ``task_dependency`` table).
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import OriginKind, Task, TaskPriority, TaskStatus
from chorus.ledger.repos._base import from_iso, to_iso, utcnow_iso
from chorus.lifecycle._transitions import assert_legal

# Statuses from which a task may be checked out into agent-owned in_progress (spec 02 §2).
_CLAIMABLE: tuple[str, ...] = ("backlog", "todo", "blocked", "in_review")

# Timestamp column stamped when entering a given status.
_STATUS_STAMP: dict[str, str] = {
    "in_progress": "started_at",
    "done": "completed_at",
    "cancelled": "cancelled_at",
}


class TaskRepo:
    """Durable operations on ``task`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def submit(self, task: Task) -> Task:
        """Insert a task. Exact-once for self-spawned work via the origin partial-unique indexes."""
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO task (id, parent_id, goal_id, intent, status, priority, "
            "assignee_employee_id, assignee_user_id, checkout_run_id, execution_run_id, depth, "
            "request_depth, origin_kind, origin_id, origin_fingerprint, created_by_employee_id, "
            "created_by_user_id, created_at, updated_at, started_at, completed_at, cancelled_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task.id,
                task.parent_id,
                task.goal_id,
                task.intent,
                task.status.value,
                task.priority.value,
                task.assignee_employee_id,
                task.assignee_user_id,
                task.checkout_run_id,
                task.execution_run_id,
                task.depth,
                task.request_depth,
                task.origin_kind.value,
                task.origin_id,
                task.origin_fingerprint,
                task.created_by_employee_id,
                task.created_by_user_id,
                to_iso(task.created_at) or now,
                to_iso(task.updated_at) or now,
                to_iso(task.started_at),
                to_iso(task.completed_at),
                to_iso(task.cancelled_at),
            ),
        )
        self._conn.commit()
        return task

    def get(self, task_id: str) -> Task | None:
        row = self._conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return _row_to_task(row) if row is not None else None

    def checkout(self, task_id: str, *, employee_id: str, run_id: str) -> bool:
        """Atomically claim a task. Returns ``False`` (a 409) if a live owner already holds it."""
        now = utcnow_iso()
        placeholders = ", ".join("?" for _ in _CLAIMABLE)
        cursor = self._conn.execute(
            "UPDATE task SET checkout_run_id = ?, execution_run_id = ?, status = 'in_progress', "
            "assignee_employee_id = ?, started_at = COALESCE(started_at, ?), updated_at = ? "
            "WHERE id = ? AND checkout_run_id IS NULL AND assignee_user_id IS NULL "
            f"AND status IN ({placeholders})",
            (run_id, run_id, employee_id, now, now, task_id, *_CLAIMABLE),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def release_locks(self, task_id: str, *, run_id: str) -> None:
        """Compare-and-clear: only release locks still pointing at ``run_id`` (spec 01 invariant 4)."""
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE task SET checkout_run_id = NULL, updated_at = ? "
            "WHERE id = ? AND checkout_run_id = ?",
            (now, task_id, run_id),
        )
        self._conn.execute(
            "UPDATE task SET execution_run_id = NULL, updated_at = ? "
            "WHERE id = ? AND execution_run_id = ?",
            (now, task_id, run_id),
        )
        self._conn.commit()

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        """Transition a task, stamping the matching ``*_at`` column (spec 02 §2)."""
        now = utcnow_iso()
        stamp = _STATUS_STAMP.get(status.value)
        if stamp is not None:
            self._conn.execute(
                f"UPDATE task SET status = ?, updated_at = ?, {stamp} = COALESCE({stamp}, ?) "
                "WHERE id = ?",
                (status.value, now, now, task_id),
            )
        else:
            self._conn.execute(
                "UPDATE task SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, task_id),
            )
        self._conn.commit()

    def transition(self, task_id: str, target: TaskStatus) -> None:
        """Guarded status PATCH — reject an illegal edge before writing (spec 02 §2).

        The status machine vets ``current → target`` (and forbids a bare PATCH into
        ``in_progress`` — that path is :meth:`checkout` only); only then does it
        delegate to :meth:`set_status` to write + stamp. Raises
        :class:`~chorus.lifecycle.IllegalTransition` on an illegal edge and
        ``KeyError`` for an unknown task — the row is left untouched in both cases.
        """
        task = self.get(task_id)
        if task is None:
            raise KeyError(task_id)
        assert_legal(task.status, target)
        self.set_status(task_id, target)

    def assign(self, task_id: str, employee_id: str) -> bool:
        """Assign a non-terminal task to an employee, moving ``backlog`` → ``todo`` (spec 03 §2).

        Sets the single employee assignee (clearing any human assignee, single-assignee XOR) and, if
        the task is parked in ``backlog``, makes it actionable. Returns ``False`` for an unknown or
        terminal task — the wake-producing caller treats that as "nothing to wake".
        """
        now = utcnow_iso()
        cursor = self._conn.execute(
            "UPDATE task SET assignee_employee_id = ?, assignee_user_id = NULL, "
            "status = CASE WHEN status = 'backlog' THEN 'todo' ELSE status END, updated_at = ? "
            "WHERE id = ? AND status NOT IN ('done', 'cancelled')",
            (employee_id, now, task_id),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def all_children_terminal(self, parent_id: str) -> bool:
        """True iff ``parent_id`` has children and every child is terminal (``done``/``cancelled``).

        The ``children_done`` signal: false when the parent has no children, so a childless task
        never spuriously wakes a parent.
        """
        row = self._conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN status IN ('done', 'cancelled') THEN 1 ELSE 0 END) AS terminal "
            "FROM task WHERE parent_id = ?",
            (parent_id,),
        ).fetchone()
        total = int(row["total"])
        return total > 0 and total == int(row["terminal"])

    def list_eligible(self, *, limit: int) -> list[Task]:
        """Unclaimed ``todo`` tasks whose blockers are all ``done``, priority then age (spec 03 §3).

        A task with any blocker not yet ``done`` (``cancelled`` does not count — spec 02 §2) is
        withheld, so the scheduler never queues a run for blocked work.
        """
        rows = self._conn.execute(
            "SELECT * FROM task t WHERE t.status = 'todo' AND t.checkout_run_id IS NULL "
            "AND t.assignee_user_id IS NULL "  # human-owned tasks aren't agent-claimable
            "AND NOT EXISTS ("
            "  SELECT 1 FROM task_dependency d JOIN task b ON b.id = d.depends_on_id "
            "  WHERE d.task_id = t.id AND b.status <> 'done'"
            ") "
            "ORDER BY CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 "
            "WHEN 'medium' THEN 2 ELSE 3 END, t.created_at LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def agent_owned_open(self) -> list[Task]:
        """Employee-owned, non-terminal, non-parked tasks - the recovery sweep's scan set (spec 02 §7).

        Excludes ``backlog`` (parked), ``done``/``cancelled`` (terminal), and human-held work
        (``assignee_user_id`` set) - the sweep never treats human-owned work as beat-managed (§8).
        """
        rows = self._conn.execute(
            "SELECT * FROM task WHERE assignee_employee_id IS NOT NULL "
            "AND assignee_user_id IS NULL "
            "AND status IN ('todo', 'in_progress', 'in_review', 'blocked') "
            "ORDER BY created_at, id"
        ).fetchall()
        return [_row_to_task(row) for row in rows]

    def has_open_for_routine(self, routine_id: str) -> bool:
        """True iff a non-terminal task spawned by this routine is still live (spec 03 §4).

        The ``skip_if_active`` gate: a routine firing while its prior task is still open is suppressed
        rather than duplicated (complements the ``task_open_routine_uq`` exact-once index).
        """
        row = self._conn.execute(
            "SELECT 1 FROM task WHERE origin_kind = 'routine_execution' AND origin_id = ? "
            "AND status NOT IN ('done', 'cancelled') LIMIT 1",
            (routine_id,),
        ).fetchone()
        return row is not None


def _row_to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=row["id"],
        intent=row["intent"],
        status=TaskStatus(row["status"]),
        priority=TaskPriority(row["priority"]),
        assignee_employee_id=row["assignee_employee_id"],
        assignee_user_id=row["assignee_user_id"],
        goal_id=row["goal_id"],
        parent_id=row["parent_id"],
        depth=row["depth"],
        request_depth=row["request_depth"],
        origin_kind=OriginKind(row["origin_kind"]),
        origin_id=row["origin_id"],
        origin_fingerprint=row["origin_fingerprint"],
        checkout_run_id=row["checkout_run_id"],
        execution_run_id=row["execution_run_id"],
        created_by_employee_id=row["created_by_employee_id"],
        created_by_user_id=row["created_by_user_id"],
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
        started_at=from_iso(row["started_at"]),
        completed_at=from_iso(row["completed_at"]),
        cancelled_at=from_iso(row["cancelled_at"]),
    )
