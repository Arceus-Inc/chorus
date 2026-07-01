"""The Marketer — the growth role that turns intent into reach, under a gate (design doc §01-§15).

One employee = one configured dream harness. This package gathers *everything* that makes a
Marketer that harness, one component per module:

- :mod:`._brief`    — the operating brief (system prompt) + the conventional content-doc filename.
- :mod:`._harness`  — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`      — the Definition of Done (intent -> typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`   — the ``content`` :class:`~chorus.outcomes.OutcomeLander` (committed draft).
- :mod:`._routines` — standing routines (performance watch, experiment readout, etc.).
- :mod:`._subagents` — Tier-1 subagents (Brand-Critic).

:func:`marketer_plugin` assembles the role triple; :func:`marketer_lander` provides the matching
:class:`~chorus.outcomes.OutcomeLander`. This is the **single source** of the Marketer:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.marketer._brief import MARKETER_BRIEF, MARKETER_CONTENT_DOC
from chorus_employee.marketer._dod import marketer_dod
from chorus_employee.marketer._harness import marketer_manifest
from chorus_employee.marketer._lander import MarketerLander, marketer_lander
from chorus_employee.marketer._routines import MARKETER_BRAND_DRIFT_SCAN, MARKETER_ROUTINES
from chorus_employee.marketer._subagents import BRAND_CRITIC_SUBAGENT


def marketer_plugin() -> RolePlugin:
    """The registrable Marketer role — manifest + DoD + outcome kind (design doc §02)."""
    return RolePlugin(
        name="marketer",
        manifest=marketer_manifest(),
        dod_generator=marketer_dod,
        outcome_kind="content",
        declared_routines=MARKETER_ROUTINES,
    )


__all__ = [
    "BRAND_CRITIC_SUBAGENT",
    "MARKETER_BRAND_DRIFT_SCAN",
    "MARKETER_BRIEF",
    "MARKETER_CONTENT_DOC",
    "MARKETER_ROUTINES",
    "MarketerLander",
    "marketer_lander",
    "marketer_plugin",
]
