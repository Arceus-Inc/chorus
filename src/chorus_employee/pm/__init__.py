"""The PM — the planning role that turns a goal into a written spec (spec 06 §2, spec 13 §4).

One employee = one configured dream harness. This package gathers everything that makes a PM that
harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt) + the conventional plan-doc filename.
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`  — the ``doc`` :class:`~chorus.outcomes.OutcomeLander` (its committed plan file).

:func:`pm_plugin` assembles the role triple. This is the **single source** of the PM:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.pm._brief import PM_BRIEF, PM_PLAN_DOC
from chorus_employee.pm._dod import pm_dod
from chorus_employee.pm._harness import pm_manifest
from chorus_employee.pm._lander import PmLander, pm_lander


def pm_plugin() -> RolePlugin:
    """The registrable PM role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="pm",
        manifest=pm_manifest(),
        dod_generator=pm_dod,
        outcome_kind="doc",
    )


__all__ = ["PM_BRIEF", "PM_PLAN_DOC", "PmLander", "pm_lander", "pm_plugin"]
