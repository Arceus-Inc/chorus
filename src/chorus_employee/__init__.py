"""chorus_employee — concrete employee definitions, one configured dream harness each.

An *employee role* is the unit of heterogeneity (spec 06 §2): a ``RoleManifest`` (the full
``build_harness`` identity) + a DoD generator + an outcome kind. This package is the home for
those concrete definitions, one package per role as the org scales. The :mod:`.engineer`
subpackage is the first; it is the **single source** the kernel's :func:`chorus.roles.default_roles`
imports the Engineer from.

This package depends on :mod:`chorus.roles` (the machinery), never the reverse — the only edge
into the kernel is ``default_roles`` reaching here for the one concrete Engineer instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.outcomes import LanderRegistry
from chorus.roles._plugin import RolePlugin
from chorus_employee.engineer import engineer_lander, engineer_plugin

if TYPE_CHECKING:
    from pathlib import Path


def default_landers(company_root: Path) -> LanderRegistry:
    """The default outcome landers, keyed by ``outcome_kind`` (spec 04 §2).

    Today the Engineer's ``pr`` lander; as employees that land artifacts are added, each registers its
    lander here — the kernel dispatches landing through the registry with no scheduler change.
    """
    return LanderRegistry.from_landers([engineer_lander(company_root)])


def default_employees() -> tuple[RolePlugin, ...]:
    """The default employee roster — the kernel's registered roles, Engineer sourced from here.

    A thin roster view over :func:`chorus.roles.default_roles` (imported lazily so importing this
    package never races the kernel's role assembly). As more roles move into ``chorus_employee``,
    this becomes the authoritative roster; today it simply *is* the kernel default set.
    """
    from chorus.roles import default_roles

    return default_roles()


__all__ = ["default_employees", "default_landers", "engineer_plugin"]
