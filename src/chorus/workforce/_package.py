"""``copy_org`` — the codec between the live ledger store and the portable git-markdown form.

"Org as data" (spec 09 §3): the git-markdown tree is the *serialization* of the live ledger org,
not a second store. ``copy_org`` is the one engine both directions share —

    export  =  copy_org(ledger_workforce, git_workforce)   # live → portable tree
    import  =  copy_org(git_workforce, ledger_workforce)    # portable tree → fresh ledger

Because every :class:`~chorus.workforce.Workforce` keys employees by ``slugify(name)`` and carries
``reports_to`` as the parent's slug, the org structure round-trips. Employees are written **managers
before reports**, so each ``reports_to`` edge resolves at the moment its report is hired.
"""

from __future__ import annotations

from chorus.errors import OrgInvariantViolation
from chorus.workforce._models import Employee
from chorus.workforce._protocol import Workforce


def copy_org(source: Workforce, dest: Workforce) -> int:
    """Copy every non-terminated employee from ``source`` into ``dest``, parents first.

    Returns the number of employees copied. Raises :class:`OrgInvariantViolation` if ``source``
    carries a ``reports_to`` cycle; the underlying ``dest.hire`` raises if a ``reports_to`` names a
    manager that is absent from the copied set (a dangling edge).
    """
    employees = source.list()
    for employee in _parents_first(employees):
        dest.hire(name=employee.name, role=employee.role, reports_to=employee.reports_to)
    return len(employees)


def _parents_first(employees: list[Employee]) -> list[Employee]:
    """Order ``employees`` so every manager precedes its reports (Kahn over ``reports_to``).

    A report whose manager is *not in the set* (a root, or a dangling/terminated parent) is treated
    as immediately placeable — the order is still valid, and a truly missing parent surfaces loudly
    at ``hire`` time rather than being silently reparented.
    """
    known = {e.id for e in employees}
    ordered: list[Employee] = []
    placed: set[str] = set()
    pending = list(employees)
    while pending:
        ready = [
            e
            for e in pending
            if e.reports_to is None or e.reports_to not in known or e.reports_to in placed
        ]
        if not ready:
            raise OrgInvariantViolation("source org has a reports_to cycle")
        for employee in ready:
            ordered.append(employee)
            placed.add(employee.id)
        pending = [e for e in pending if e.id not in placed]
    return ordered


__all__ = ["copy_org"]
