"""The Analyst — the research role that turns a question into written findings (spec 06 §2, spec 13 §4).

One employee = one configured dream harness. This package gathers everything that makes an Analyst
that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt) + the conventional findings-doc filename.
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`  — the ``finding`` :class:`~chorus.outcomes.OutcomeLander` (its committed findings file).

:func:`analyst_plugin` assembles the role triple. This is the **single source** of the Analyst:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.analyst._brief import ANALYST_BRIEF, ANALYST_FINDINGS_DOC
from chorus_employee.analyst._dod import analyst_dod
from chorus_employee.analyst._harness import analyst_manifest
from chorus_employee.analyst._lander import AnalystLander, analyst_lander


def analyst_plugin() -> RolePlugin:
    """The registrable Analyst role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="analyst",
        manifest=analyst_manifest(),
        dod_generator=analyst_dod,
        outcome_kind="finding",
    )


__all__ = [
    "ANALYST_BRIEF",
    "ANALYST_FINDINGS_DOC",
    "AnalystLander",
    "analyst_lander",
    "analyst_plugin",
]
