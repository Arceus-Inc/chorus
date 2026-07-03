"""The Analyst — the research role that turns a question into written findings (spec 06 §2, spec 13 §4).

One employee = one configured dream harness. This package gathers everything that makes an Analyst
that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt) + the conventional findings-doc filename.
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the action-class-aware DoD (Command | AgentReview | HumanApproval).
- :mod:`._lander`  — the ``finding`` :class:`~chorus.outcomes.OutcomeLander` (its committed findings file).
- :mod:`._integrations` — the trust-scoped read WebPlugins (warehouse + web) + per-subagent grants.

:func:`analyst_plugin` assembles the role triple. This is the **single source** of the Analyst:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.analyst._brief import ANALYST_BRIEF, ANALYST_FINDINGS_DOC
from chorus_employee.analyst._dod import ActionClass, analyst_dod, classify_action
from chorus_employee.analyst._harness import analyst_manifest
from chorus_employee.analyst._integrations import analyst_webplugins, subagent_grants
from chorus_employee.analyst._lander import AnalystLander, analyst_lander
from chorus_employee.analyst._routines import ANALYST_ROUTINES


def analyst_plugin() -> RolePlugin:
    """The registrable Analyst role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="analyst",
        manifest=analyst_manifest(),
        dod_generator=analyst_dod,
        outcome_kind="finding",
        declared_routines=ANALYST_ROUTINES,
    )


__all__ = [
    "ANALYST_BRIEF",
    "ANALYST_FINDINGS_DOC",
    "ANALYST_ROUTINES",
    "ActionClass",
    "AnalystLander",
    "analyst_lander",
    "analyst_plugin",
    "analyst_webplugins",
    "classify_action",
    "subagent_grants",
]
