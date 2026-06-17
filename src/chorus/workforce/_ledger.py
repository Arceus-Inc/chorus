"""The ledger-backed default ``Workforce`` (spec 06 §3) — the single live org store.

The ledger ``employee`` table is the runtime source of truth: every ownership/assignment FK
(``task.assignee_employee_id``, ``run.employee_id``, ``wake.employee_id``, ``employee.reports_to``)
points at it, so the org the scheduler dispatches against and the org a human edits must be the *same*
rows. :class:`LedgerWorkforce` is that store — hire/terminate are data edits on the ledger, and the
structural invariants (no ``reports_to`` cycle / self-edge, no duplicate slug, ``terminate`` is
irreversible, the root cannot be terminated) live here, not in the row-I/O repo.

It depends on a narrow :class:`EmployeeStore` (the slice of the ledger employee repo it needs),
injected at construction — so the dependency points *into* the kernel (the ledger repo never imports
the workforce) and the workforce is unit-testable against a fake store. The portable git-markdown
form (:class:`~chorus.workforce.GitWorkforce`) is the *export/import* serialization of this store
(spec 09 §3), not a second live store.
"""

from __future__ import annotations

from typing import Protocol

from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.workforce._models import Employee, EmployeeStatus
from chorus.workforce._slug import slugify


class EmployeeStore(Protocol):
    """The slice of the ledger employee repo :class:`LedgerWorkforce` drives (spec 01 Cluster D)."""

    def get(self, employee_id: str) -> Employee | None: ...

    def create(self, employee: Employee) -> Employee: ...

    def list(self) -> list[Employee]: ...

    def set_status(self, employee_id: str, status: EmployeeStatus) -> None: ...


class LedgerWorkforce:
    """The ledger-backed :class:`~chorus.workforce.Workforce` (spec 06 §3) — the live org store."""

    def __init__(self, store: EmployeeStore) -> None:
        self._store = store

    def get(self, employee_id: str) -> Employee:
        employee = self._store.get(employee_id)
        if employee is None:
            raise UnknownEmployee(f"no employee {employee_id!r}")
        return employee

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        slug = slugify(name)
        if not slug:
            raise OrgInvariantViolation(f"name {name!r} produces an empty slug")
        if reports_to == slug:
            raise OrgInvariantViolation(f"{slug!r} cannot report to itself")
        if self._store.get(slug) is not None:
            raise OrgInvariantViolation(f"employee slug {slug!r} already exists")
        if reports_to is not None and self._store.get(reports_to) is None:
            raise UnknownEmployee(f"reports_to {reports_to!r} does not exist")
        self._store.create(
            Employee(
                id=slug,
                name=name,
                role=role,
                reports_to=reports_to,
                memory_scope="project",
                status=EmployeeStatus.IDLE,
            )
        )
        return self.get(slug)  # read-after-write: return the canonical persisted row

    def terminate(self, employee_id: str) -> None:
        employee = self.get(employee_id)
        if employee.status is EmployeeStatus.TERMINATED:
            return  # irreversible — repeating is a harmless no-op
        if employee.reports_to is None:
            raise OrgInvariantViolation(f"the org root {employee_id!r} cannot be terminated")
        self._store.set_status(employee_id, EmployeeStatus.TERMINATED)

    def list(self) -> list[Employee]:
        return [e for e in self._store.list() if e.status is not EmployeeStatus.TERMINATED]


__all__ = ["EmployeeStore", "LedgerWorkforce"]
