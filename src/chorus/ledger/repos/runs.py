"""RunRepo — one beat per row, kept THIN (spec 01 Cluster C ``run``)."""

from __future__ import annotations

import sqlite3

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
            "UPDATE run SET status = ?, liveness_state = ?, "
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
