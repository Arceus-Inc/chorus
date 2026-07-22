"""chorus_employee — concrete employee definitions, one configured dream harness each.

An *employee role* is the unit of heterogeneity (spec 06 §2): a ``RoleManifest`` (the full
``build_harness`` identity) + a DoD generator + an outcome kind. This package is the home for
those concrete definitions, one package per role as the org scales. Canonical defaults use specific
professions; the generic :mod:`.engineer` package remains available for explicit compatibility
registration.

This package depends on :mod:`chorus.roles` (the machinery), while the kernel's lazy default-role
assembly imports the concrete profession plugins from here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.outcomes import LanderRegistry, OutcomeLander
from chorus.roles._plugin import RolePlugin
from chorus_employee.analyst import analyst_lander
from chorus_employee.ceo import ceo_lander
from chorus_employee.designer import designer_lander
from chorus_employee.engineer import engineer_lander, engineer_plugin
from chorus_employee.manager import manager_lander
from chorus_employee.marketer import marketer_lander
from chorus_employee.pm import pm_lander

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Ledger


def default_landers(company_root: Path, *, ledger: Ledger | None = None) -> LanderRegistry:
    """The default outcome landers, keyed by ``outcome_kind`` (spec 04 §2).

    The engineering ``pr`` lander, the PM's ``doc`` lander, and the Analyst's ``finding`` lander always
    (each only needs the org workspace); the Manager's ``subtree`` lander when a ``ledger`` is supplied
    (it reads its delegated children from there). As employees that land artifacts are added, each
    registers its lander here — the kernel dispatches landing through the registry with no scheduler
    change.
    """
    landers: list[OutcomeLander] = [
        engineer_lander(company_root, ledger),
        pm_lander(
            company_root, ledger
        ),  # ledger (when present) also renders the §10 decision packet
        analyst_lander(company_root, ledger),
        marketer_lander(company_root, ledger),
        designer_lander(company_root, ledger),
        ceo_lander(company_root, ledger),
    ]
    if ledger is not None:
        landers.append(manager_lander(ledger))
    return LanderRegistry.from_landers(landers)


def default_employees() -> tuple[RolePlugin, ...]:
    """The canonical employee roster assembled by the kernel's default-role registry.

    A thin roster view over :func:`chorus.roles.default_roles` (imported lazily so importing this
    package never races the kernel's role assembly). As more roles move into ``chorus_employee``,
    this becomes the authoritative roster; today it simply *is* the kernel default set.
    """
    from chorus.roles import default_roles

    return default_roles()


__all__ = ["default_employees", "default_landers", "engineer_plugin"]
