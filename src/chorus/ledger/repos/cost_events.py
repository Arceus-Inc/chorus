"""CostEventRepo — the immutable spend ledger (spec 01 Cluster E ``cost_event``, spec 04).

``record`` appends one immutable spend row. ``spent_cents`` recomputes an employee's spend live by
summing cost_events — never a trusted stored counter (the Paperclip rule). An optional ``since`` bound
scopes the sum to the live budget window.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger._models import CostEvent
from chorus.ledger.repos._base import from_iso, to_iso, utcnow_iso


class CostEventRepo:
    """Append + aggregate ``cost_event`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, event: CostEvent) -> CostEvent:
        """Append one immutable spend record."""
        occurred = to_iso(event.occurred_at) or utcnow_iso()
        self._conn.execute(
            "INSERT INTO cost_event (id, employee_id, task_id, run_id, provider, model, "
            "input_tokens, output_tokens, cost_cents, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.employee_id,
                event.task_id,
                event.run_id,
                event.provider,
                event.model,
                event.input_tokens,
                event.output_tokens,
                event.cost_cents,
                occurred,
            ),
        )
        self._conn.commit()
        recorded = self.get(event.id)
        assert recorded is not None  # just inserted in this transaction
        return recorded

    def get(self, event_id: str) -> CostEvent | None:
        row = self._conn.execute(
            "SELECT * FROM cost_event WHERE id = ?", (event_id,)
        ).fetchone()
        return _row_to_event(row) if row is not None else None

    def spent_cents(self, employee_id: str, *, since: datetime | None = None) -> int:
        """Live-recomputed spend for an employee, optionally bounded to a window start."""
        if since is None:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_cents), 0) AS total FROM cost_event WHERE employee_id = ?",
                (employee_id,),
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_cents), 0) AS total FROM cost_event "
                "WHERE employee_id = ? AND occurred_at >= ?",
                (employee_id, to_iso(since)),
            ).fetchone()
        return int(row["total"])


def _row_to_event(row: sqlite3.Row) -> CostEvent:
    return CostEvent(
        id=row["id"],
        employee_id=row["employee_id"],
        provider=row["provider"],
        model=row["model"],
        cost_cents=row["cost_cents"],
        task_id=row["task_id"],
        run_id=row["run_id"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        occurred_at=from_iso(row["occurred_at"]),
    )
