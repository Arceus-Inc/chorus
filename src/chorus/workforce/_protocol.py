"""The ``Workforce`` seam — the swappable org-as-data store behind the facade (spec 06 §3)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chorus.workforce._models import Employee, EmployeeStatus


@runtime_checkable
class Workforce(Protocol):
    """The org-as-data store (spec 06 §3) — the swappable seam behind the facade."""

    def get(self, employee_id: str) -> Employee:
        """Fetch one employee row."""
        ...

    def hire(
        self,
        *,
        name: str,
        role: str,
        reports_to: str | None = None,
        status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> Employee:
        """Add an employee; rejects a ``reports_to`` cycle (``OrgInvariantViolation``).

        ``status`` is ``idle`` for a direct hire, ``pending`` for a governed one (spec 04 §5)."""
        ...

    def terminate(self, employee_id: str) -> None:
        """Mark an employee terminated — irreversible; the root cannot be terminated."""
        ...

    def list(self) -> list[Employee]:
        """All non-terminated employees."""
        ...


__all__ = ["Workforce"]
