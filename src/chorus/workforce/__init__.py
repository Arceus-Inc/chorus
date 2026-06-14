"""The Workforce — org as data (spec 06 §3).

The org chart **is** the ``employee.reports_to`` adjacency list — there is no
``teams`` table; team structure is emergent. Hire/fire is a data edit, not a
process spawn. An :class:`Employee` has no continuous existence: each beat
*rehydrates* it from ``(employee row + role manifest + memory scope + ledger
history)``, runs one ``run_task``, and dissolves (B1.1). Continuity lives in the
ledger + memory git, never in a running thing.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class EmployeeStatus(StrEnum):
    """An employee's lifecycle (spec 01 Cluster D ``employee.status``)."""

    IDLE = "idle"
    ACTIVE = "active"
    RUNNING = "running"
    PAUSED = "paused"
    ERROR = "error"
    TERMINATED = "terminated"


@dataclass(frozen=True)
class Employee:
    """A replayable identity, not a process (spec 06 §1).

    ``reports_to`` is the org-chart edge (no cycles; ``terminated`` is
    irreversible — spec 06 §3). Budget columns are advisory mirrors;
    ``spent_monthly_cents`` is always recomputed live from ``cost_event`` on read,
    never trusted (spec 04 §3).
    """

    id: str
    name: str
    role: str
    reports_to: str | None = None
    memory_scope: str = "project"
    status: EmployeeStatus = EmployeeStatus.IDLE
    budget_monthly_cents: int | None = None
    spent_monthly_cents: int = 0
    last_beat_at: str | None = None


@runtime_checkable
class Workforce(Protocol):
    """The org-as-data store (spec 06 §3) — the swappable seam behind the facade."""

    def get(self, employee_id: str) -> Employee:
        """Fetch one employee row."""
        ...

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        """Add an employee; rejects a ``reports_to`` cycle (``OrgInvariantViolation``)."""
        ...

    def terminate(self, employee_id: str) -> None:
        """Mark an employee terminated — irreversible; the root cannot be terminated."""
        ...

    def list(self) -> list[Employee]:
        """All non-terminated employees."""
        ...


class GitWorkforce:
    """The git-markdown default ``Workforce`` (spec 06 §3, spec 09 §3).

    Each employee is an ``employees/<slug>/role.md`` with frontmatter
    (``role``, ``reports_to_slug``, ``memory_scope``, ``skills``); the tree is the
    portable-package format export/imports (spec 09 §3).
    """

    def __init__(self, org_repo: str) -> None:
        self.org_repo = org_repo

    def get(self, employee_id: str) -> Employee:
        raise NotImplementedError("spec 06 §3: read employee row")

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        raise NotImplementedError("spec 06 §3: append employee, validate org chain (no cycles)")

    def terminate(self, employee_id: str) -> None:
        raise NotImplementedError("spec 06 §3: irreversible terminate")

    def list(self) -> list[Employee]:
        raise NotImplementedError("spec 06 §3: enumerate the org tree")


__all__ = [
    "Employee",
    "EmployeeStatus",
    "GitWorkforce",
    "Workforce",
]
