"""CostEventRepo — the immutable spend ledger (spec 01 Cluster E ``cost_event``, spec 04).

``record`` appends one immutable spend row. ``spent_cents`` recomputes an employee's spend live by
summing cost_events — never a trusted stored counter (the Paperclip rule). An optional ``since`` bound
scopes the sum to the live budget window.
"""

from __future__ import annotations

from datetime import datetime

from chorus.ledger._models import CostEvent
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    to_iso,
    utcnow_iso,
)


class CostEventRepo:
    """Append + aggregate ``cost_event`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def record(self, event: CostEvent) -> CostEvent:
        """Append one immutable spend record; ``cost_cents`` must be non-negative."""
        if event.cost_cents < 0:
            raise ValueError("cost_cents must be non-negative")
        occurred = to_iso(event.occurred_at) or utcnow_iso()
        self._conn.execute(
            "INSERT INTO cost_event (id, employee_id, task_id, run_id, trace_id, provider, model, "
            "input_tokens, output_tokens, cost_cents, occurred_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event.id,
                event.employee_id,
                event.task_id,
                event.run_id,
                event.trace_id,
                event.provider,
                event.model,
                event.input_tokens,
                event.output_tokens,
                event.cost_cents,
                occurred,
            ),
        )
        self._conn.commit()
        recorded = require_persisted(self.get(event.id), event.id)
        return recorded

    def get(self, event_id: str) -> CostEvent | None:
        row = self._conn.execute("SELECT * FROM cost_event WHERE id = ?", (event_id,)).fetchone()
        return _row_to_event(row) if row is not None else None

    def for_run(self, run_id: str) -> list[CostEvent]:
        """Every cost event a run recorded, oldest first — the run's spend, itemised."""
        rows = self._conn.execute(
            "SELECT * FROM cost_event WHERE run_id = ? ORDER BY occurred_at, id", (run_id,)
        ).fetchall()
        return [_row_to_event(row) for row in rows]

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

    def total_spent_cents(self, *, since: datetime | None = None) -> int:
        """Live-recomputed spend across the *whole* workforce — the company-scope sum (spec 04 §3)."""
        if since is None:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_cents), 0) AS total FROM cost_event"
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT COALESCE(SUM(cost_cents), 0) AS total FROM cost_event WHERE occurred_at >= ?",
                (to_iso(since),),
            ).fetchone()
        return int(row["total"])


def _row_to_event(row: LedgerRow) -> CostEvent:
    return CostEvent(
        id=row["id"],
        employee_id=row["employee_id"],
        provider=row["provider"],
        model=row["model"],
        cost_cents=row["cost_cents"],
        task_id=row["task_id"],
        run_id=row["run_id"],
        trace_id=row["trace_id"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        occurred_at=from_iso(row["occurred_at"]),
    )
