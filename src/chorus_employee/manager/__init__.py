"""The Manager — the orchestrator role (spec 06 §2, spec 11 §M3).

One employee = one configured dream harness. This package gathers everything that makes a Manager
that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt).
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`  — the ``subtree`` :class:`~chorus.outcomes.OutcomeLander` (its completed subtree).

:func:`manager_plugin` assembles the role triple. This is the **single source** of the Manager:
``chorus.roles.default_roles`` imports the plugin from here.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.manager._dod import manager_dod
from chorus_employee.manager._harness import manager_manifest
from chorus_employee.manager._lander import ManagerLander, manager_lander
from chorus_employee.manager._routines import MANAGER_ROUTINES


def manager_plugin() -> RolePlugin:
    """The registrable Manager role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="manager",
        manifest=manager_manifest(),
        dod_generator=manager_dod,
        outcome_kind="subtree",
        declared_routines=MANAGER_ROUTINES,
    )


__all__ = ["MANAGER_ROUTINES", "ManagerLander", "manager_lander", "manager_plugin"]
