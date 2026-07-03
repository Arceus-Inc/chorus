"""EmployeeRepo — persistence for the Workforce (spec 01 Cluster D, spec 06).

The :class:`~chorus.workforce.Employee` *model* lives in ``chorus.workforce``; this repo is its
ledger persistence. Org-invariant checks (no ``reports_to`` cycle, irreversible terminate) belong
to the Workforce layer (spec 06 §3), not here — this is plain row I/O.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger.repos._base import utcnow_iso
from chorus.workforce import Employee, EmployeeStatus


class EmployeeRepo:
    """Create + read ``employee`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, employee: Employee) -> Employee:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO employee (id, name, role, reports_to, memory_scope, status, "
            "budget_monthly_cents, spent_monthly_cents, last_beat_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                employee.id,
                employee.name,
                employee.role,
                employee.reports_to,
                employee.memory_scope,
                employee.status.value,
                employee.budget_monthly_cents or 0,
                employee.spent_monthly_cents,
                employee.last_beat_at,
                now,
                now,
            ),
        )
        self._conn.commit()
        return employee

    def get(self, employee_id: str) -> Employee | None:
        row = self._conn.execute("SELECT * FROM employee WHERE id = ?", (employee_id,)).fetchone()
        return _row_to_employee(row) if row is not None else None

    def list(self) -> list[Employee]:
        """Every employee row (terminated included) — the Workforce layer filters."""
        rows = self._conn.execute("SELECT * FROM employee ORDER BY id").fetchall()
        return [_row_to_employee(row) for row in rows]

    def set_status(self, employee_id: str, status: EmployeeStatus) -> None:
        """Transition one employee's lifecycle status (spec 01 Cluster D)."""
        self._conn.execute(
            "UPDATE employee SET status = ?, updated_at = ? WHERE id = ?",
            (status.value, utcnow_iso(), employee_id),
        )
        self._conn.commit()


def _row_to_employee(row: sqlite3.Row) -> Employee:
    return Employee(
        id=row["id"],
        name=row["name"],
        role=row["role"],
        reports_to=row["reports_to"],
        memory_scope=row["memory_scope"],
        status=EmployeeStatus(row["status"]),
        budget_monthly_cents=row["budget_monthly_cents"],
        spent_monthly_cents=row["spent_monthly_cents"],
        last_beat_at=row["last_beat_at"],
    )
