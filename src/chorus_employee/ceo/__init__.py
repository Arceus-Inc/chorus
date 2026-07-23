"""The CEO — the executive role that turns the company's state into a decisive directive (spec 06 §2).

One employee = one configured dream harness. This package gathers everything that makes a CEO that
harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt) + the conventional directive-doc filename.
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the action-class-aware DoD (AgentReview directive | HumanApproval commitment).
- :mod:`._lander`  — the ``directive`` :class:`~chorus.outcomes.OutcomeLander` (its committed directive).

:func:`ceo_plugin` assembles the role triple. This is the **single source** of the CEO:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.ceo._brief import CEO_BRIEF, CEO_DIRECTIVE_DOC
from chorus_employee.ceo._dod import ActionClass, ceo_dod, classify_action
from chorus_employee.ceo._harness import ceo_manifest
from chorus_employee.ceo._lander import CeoLander, ceo_lander
from chorus_employee.ceo._routines import CEO_ROUTINES


def ceo_plugin() -> RolePlugin:
    """The registrable CEO role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="ceo",
        manifest=ceo_manifest(),
        dod_generator=ceo_dod,
        outcome_kind="directive",
        declared_routines=CEO_ROUTINES,
    )


__all__ = [
    "CEO_BRIEF",
    "CEO_DIRECTIVE_DOC",
    "CEO_ROUTINES",
    "ActionClass",
    "CeoLander",
    "ceo_dod",
    "ceo_lander",
    "ceo_manifest",
    "ceo_plugin",
    "classify_action",
]
