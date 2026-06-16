"""The Workforce — org as data (spec 06 §3).

The org chart **is** the ``employee.reports_to`` adjacency list — there is no
``teams`` table; team structure is emergent. Hire/fire is a data edit, not a
process spawn. An :class:`Employee` has no continuous existence: each beat
*rehydrates* it from ``(employee row + role manifest + memory scope + ledger
history)``, runs one ``run_task``, and dissolves (B1.1). Continuity lives in the
ledger + memory git, never in a running thing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import yaml

from chorus.errors import OrgInvariantViolation, UnknownEmployee


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
    portable-package format export/imports (spec 09 §3). The slug *is* the id
    (``slugify(name)``), so the org survives re-import into a fresh workforce.
    """

    def __init__(self, org_repo: str) -> None:
        self.org_repo = org_repo
        self._employees_dir = Path(org_repo) / "employees"

    # -- reads ----------------------------------------------------------------

    def get(self, employee_id: str) -> Employee:
        path = self._role_md(employee_id)
        if not path.exists():
            raise UnknownEmployee(f"no employee {employee_id!r}")
        return self._read(employee_id, path)

    def list(self) -> list[Employee]:
        if not self._employees_dir.exists():
            return []
        employees = [
            self._read(child.name, child / "role.md")
            for child in sorted(self._employees_dir.iterdir())
            if (child / "role.md").exists()
        ]
        return [e for e in employees if e.status is not EmployeeStatus.TERMINATED]

    # -- writes ---------------------------------------------------------------

    def hire(self, *, name: str, role: str, reports_to: str | None = None) -> Employee:
        slug = _slugify(name)
        if not slug:
            raise OrgInvariantViolation(f"name {name!r} produces an empty slug")
        if reports_to == slug:
            raise OrgInvariantViolation(f"{slug!r} cannot report to itself")
        if self._role_md(slug).exists():
            raise OrgInvariantViolation(f"employee slug {slug!r} already exists")
        if reports_to is not None and not self._role_md(reports_to).exists():
            raise UnknownEmployee(f"reports_to {reports_to!r} does not exist")
        employee = Employee(
            id=slug,
            name=name,
            role=role,
            reports_to=reports_to,
            memory_scope="project",
            status=EmployeeStatus.IDLE,
        )
        self._write(employee)
        return employee

    def terminate(self, employee_id: str) -> None:
        employee = self.get(employee_id)
        if employee.status is EmployeeStatus.TERMINATED:
            return  # irreversible — repeating is a harmless no-op
        if employee.reports_to is None:
            raise OrgInvariantViolation(f"the org root {employee_id!r} cannot be terminated")
        self._write(
            Employee(
                id=employee.id,
                name=employee.name,
                role=employee.role,
                reports_to=employee.reports_to,
                memory_scope=employee.memory_scope,
                status=EmployeeStatus.TERMINATED,
                budget_monthly_cents=employee.budget_monthly_cents,
                spent_monthly_cents=employee.spent_monthly_cents,
                last_beat_at=employee.last_beat_at,
            )
        )

    # -- persistence ----------------------------------------------------------

    def _role_md(self, slug: str) -> Path:
        return self._employees_dir / slug / "role.md"

    def _read(self, slug: str, path: Path) -> Employee:
        front = _parse_frontmatter(path.read_text(encoding="utf-8"))
        return Employee(
            id=slug,
            name=str(front.get("name", slug)),
            role=str(front["role"]),
            reports_to=front.get("reports_to_slug") or None,
            memory_scope=str(front.get("memory_scope", "project")),
            status=EmployeeStatus(str(front.get("status", EmployeeStatus.IDLE))),
        )

    def _write(self, employee: Employee) -> None:
        path = self._role_md(employee.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        front: dict[str, Any] = {
            "name": employee.name,
            "role": employee.role,
            "reports_to_slug": employee.reports_to,
            "memory_scope": employee.memory_scope,
            "skills": [],
            "status": str(employee.status),
        }
        body = yaml.safe_dump(front, sort_keys=True, default_flow_style=False)
        path.write_text(f"---\n{body}---\n", encoding="utf-8")


def _slugify(name: str) -> str:
    """Lowercase, collapse non-alphanumeric runs to a single hyphen, strip edges."""
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Read the ``---``-delimited YAML frontmatter block; ``{}`` if absent."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1])
    return loaded if isinstance(loaded, dict) else {}


__all__ = [
    "Employee",
    "EmployeeStatus",
    "GitWorkforce",
    "Workforce",
]
