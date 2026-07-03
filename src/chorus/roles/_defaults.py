"""The v0 role plugins (spec 06 §2 table).

| Role      | Toolset leans            | DoD (verifier)          | Outcome              |
|-----------|--------------------------|-------------------------|----------------------|
| Engineer  | repo-write, run gates    | Command (CI/tests exit0)| PR opened, CI green  |
| Reviewer  | read-only                | renders the verdict     | approve/block        |
| Manager   | ledger-write (decompose) | children done+integrated| a completed subtree  |
| Product/PM| read + write docs        | AgentReview (Reviewer)  | spec/decision        |
| Analyst   | read + data tools        | AgentReview (Reviewer)  | a data finding       |
| Marketer  | read + draft-write       | AgentReview (brand)     | content draft        |

Reviewer is load-bearing, not a luxury (B3.2): it is the verifier for all
judgment-class work, so it must ship at M3 with the first non-code role.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin

# Each role owns a dedicated package under chorus_employee/. The kernel default set sources them from
# there — single source, no drift — rather than re-declaring them here. Submodule imports (not the
# chorus_employee package root) keep this edge cycle-free.
from chorus_employee.analyst import analyst_plugin
from chorus_employee.engineer import engineer_plugin
from chorus_employee.manager import manager_plugin
from chorus_employee.marketer import marketer_plugin
from chorus_employee.pm import pm_plugin
from chorus_employee.reviewer import reviewer_plugin


def default_roles() -> tuple[RolePlugin, ...]:
    """The canonical v0 workforce roles, registered at boot (spec 06 §2).

    A consumer adds a seventh role with ``chorus.workforce.register_role(...)`` — never by
    editing the kernel (spec 09 §1).
    """
    return (
        engineer_plugin(),
        reviewer_plugin(),
        manager_plugin(),
        pm_plugin(),
        analyst_plugin(),
        marketer_plugin(),
    )


__all__ = ["default_roles"]
