"""The canonical concrete workforce plugins.

| Role      | Toolset leans            | DoD (verifier)          | Outcome              |
|-----------|--------------------------|-------------------------|----------------------|
| Product/PM| read + write docs        | AgentReview (Reviewer)  | spec/decision        |
| Analyst   | read + data tools        | AgentReview (Reviewer)  | a data finding       |
| Marketer  | read + draft-write       | AgentReview (brand)     | content draft        |

Verification is performed by the non-workforce ``system-verifier`` principal. Generic ``engineer``
and employee ``reviewer`` plugins remain available for explicit legacy registration but are not new
workforce defaults.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin

# Each role owns a dedicated package under chorus_employee/. The kernel default set sources them from
# there — single source, no drift — rather than re-declaring them here. Submodule imports (not the
# chorus_employee package root) keep this edge cycle-free.
from chorus_employee.analyst import analyst_plugin
from chorus_employee.backend_engineer import backend_engineer_plugin
from chorus_employee.ceo import ceo_plugin
from chorus_employee.designer import designer_plugin
from chorus_employee.frontend_engineer import frontend_engineer_plugin
from chorus_employee.marketer import marketer_plugin
from chorus_employee.pm import pm_plugin


def default_roles() -> tuple[RolePlugin, ...]:
    """The canonical workforce professions registered at boot.

    A consumer adds a role, including a legacy compatibility role, with
    ``chorus.workforce.register_role(...)`` rather than editing the kernel (spec 09 §1).
    """
    return (
        backend_engineer_plugin(),
        pm_plugin(),
        analyst_plugin(),
        marketer_plugin(),
        designer_plugin(),
        frontend_engineer_plugin(),
        ceo_plugin(),
    )


__all__ = ["default_roles"]
