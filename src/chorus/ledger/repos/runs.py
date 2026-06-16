"""RunRepo — one beat per row, kept THIN (spec 01 Cluster C ``run``)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger._models import Run, RunStatus
from chorus.ledger.repos._base import dumps, from_iso, loads, to_iso, utcnow_iso


class RunRepo:
    """Create + read + finish ``run`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, run: Run) -> Run:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO run (id, employee_id, task_id, wake_id, status, lease_expires_at, "
            "liveness_state, continuation_attempt, outcome, usage, started_at, finished_at, "
            "created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run.id,
                run.employee_id,
                run.task_id,
                run.wake_id,
                run.status.value,
                to_iso(run.lease_expires_at),
                run.liveness_state,
                run.continuation_attempt,
                dumps(run.outcome),
                dumps(run.usage),
                to_iso(run.started_at),
                to_iso(run.finished_at),
                now,
            ),
        )
        self._conn.commit()
        return run

    def get(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM run WHERE id = ?", (run_id,)).fetchone()
        return _row_to_run(row) if row is not None else None

    def for_task(self, task_id: str) -> list[Run]:
        """All runs for a task, oldest first — the liveness/recovery history (spec 02 §3)."""
        rows = self._conn.execute(
            "SELECT * FROM run WHERE task_id = ? ORDER BY created_at, id", (task_id,)
        ).fetchall()
        return [_row_to_run(row) for row in rows]

    def count_running(self) -> int:
        """Live beats in flight — feeds ``free_slots`` (the concurrency budget gate, spec 03 §5)."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM run WHERE status = 'running'"
        ).fetchone()
        return int(row["n"])

    def running_employee_ids(self) -> set[str]:
        """Employees with a live beat — feeds the tick's per-employee serialization (spec 03 §5).

        At most one beat per employee may be in flight, so the tick skips (and re-queues) any wake
        for an employee already named here before it dispatches a fresh beat.
        """
        rows = self._conn.execute(
            "SELECT DISTINCT employee_id FROM run WHERE status = 'running'"
        ).fetchall()
        return {row["employee_id"] for row in rows}

    def running_with_expired_lease(self, now: datetime) -> list[Run]:
        """``running`` runs whose lease has passed (or was never set) - orphaned beats (spec 02 §7).

        These are crash debris: the worker died mid-beat and the lease lapsed, so the tick reaps
        them (release the lock, mark timed-out) before any new dispatch.
        """
        rows = self._conn.execute(
            "SELECT * FROM run WHERE status = 'running' "
            "AND (lease_expires_at IS NULL OR lease_expires_at < ?) "
            "ORDER BY created_at, id",
            (to_iso(now),),
        ).fetchall()
        return [_row_to_run(row) for row in rows]

    def cancel_running(self, *, employee_id: str | None = None) -> list[str]:
        """Cancel every live (``running``) run, optionally scoped to one employee (spec 04 §3 kill).

        Returns the cancelled run ids. A hard budget breach kills in-flight work for the paused
        scope; ``employee_id=None`` cancels the whole workforce (a company-scope breach).
        """
        now = utcnow_iso()
        # One atomic statement: the ``status = 'running'`` predicate lives in the UPDATE itself and
        # ``RETURNING`` reports exactly the rows it flipped — so a run that finishes concurrently is
        # never overwritten back to ``cancelled`` (no select-then-update race).
        if employee_id is None:
            rows = self._conn.execute(
                "UPDATE run SET status = 'cancelled', finished_at = ? "
                "WHERE status = 'running' RETURNING id",
                (now,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "UPDATE run SET status = 'cancelled', finished_at = ? "
                "WHERE status = 'running' AND employee_id = ? RETURNING id",
                (now, employee_id),
            ).fetchall()
        self._conn.commit()
        return [str(row["id"]) for row in rows]

    def finish(
        self,
        run_id: str,
        status: RunStatus,
        *,
        liveness_state: str | None = None,
        outcome: dict[str, object] | None = None,
        usage: dict[str, object] | None = None,
    ) -> None:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE run SET status = ?, liveness_state = COALESCE(?, liveness_state), "
            "outcome = COALESCE(?, outcome), usage = COALESCE(?, usage), finished_at = ? "
            "WHERE id = ?",
            (
                status.value,
                liveness_state,
                dumps(outcome) if outcome is not None else None,
                dumps(usage) if usage is not None else None,
                now,
                run_id,
            ),
        )
        self._conn.commit()


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        id=row["id"],
        employee_id=row["employee_id"],
        task_id=row["task_id"],
        wake_id=row["wake_id"],
        status=RunStatus(row["status"]),
        lease_expires_at=from_iso(row["lease_expires_at"]),
        liveness_state=row["liveness_state"],
        continuation_attempt=row["continuation_attempt"],
        started_at=from_iso(row["started_at"]),
        finished_at=from_iso(row["finished_at"]),
        outcome=loads(row["outcome"]) or {},
        usage=loads(row["usage"]) or {},
    )
