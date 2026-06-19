"""The git-markdown ``Workforce`` — the portable export/import form (spec 09 §3).

Not the live store: the runtime source of truth is the ledger employee table
(:class:`~chorus.workforce.LedgerWorkforce`). This is the slug-portable git-markdown
serialization of that org — what ``chorus export`` / ``chorus import`` move between
deployments — implemented over the same :class:`~chorus.workforce.Workforce` seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.workforce._models import Employee, EmployeeStatus
from chorus.workforce._slug import slugify


class GitWorkforce:
    """The git-markdown portable ``Workforce`` form (spec 06 §3, spec 09 §3).

    Each employee is an ``employees/<slug>/role.md`` with frontmatter
    (``role``, ``reports_to_slug``, ``memory_scope``, ``skills``); the tree is the
    portable-package format export/imports (spec 09 §3). The slug *is* the id
    (``slugify(name)``), so the org survives re-import into a fresh ledger. The live
    runtime store is :class:`~chorus.workforce.LedgerWorkforce`, not this.
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

    def hire(
        self,
        *,
        name: str,
        role: str,
        reports_to: str | None = None,
        status: EmployeeStatus = EmployeeStatus.IDLE,
    ) -> Employee:
        slug = slugify(name)
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
            status=status,
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


def _parse_frontmatter(text: str) -> dict[str, Any]:
    """Read the ``---``-delimited YAML frontmatter block; ``{}`` if absent."""
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1])
    return loaded if isinstance(loaded, dict) else {}


__all__ = ["GitWorkforce"]
