"""The Reviewer — the verifier for judgment-class work (spec 06 §2, B3.2).

One employee = one configured dream harness. This package gathers everything that makes a Reviewer
that harness, one component per module:

- :mod:`._brief`   — the operating brief (system prompt).
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`  — the ``verdict`` outcome lander (records the verdict artifact).

:func:`reviewer_plugin` assembles the role triple. This is the **single source** of the Reviewer:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.reviewer._dod import reviewer_dod
from chorus_employee.reviewer._harness import reviewer_manifest
from chorus_employee.reviewer._lander import ReviewerLander, reviewer_lander
from chorus_employee.reviewer._routines import REVIEWER_ROUTINES


def reviewer_plugin() -> RolePlugin:
    """The registrable Reviewer role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="reviewer",
        manifest=reviewer_manifest(),
        dod_generator=reviewer_dod,
        outcome_kind="verdict",
        declared_routines=REVIEWER_ROUTINES,
    )


__all__ = ["REVIEWER_ROUTINES", "ReviewerLander", "reviewer_lander", "reviewer_plugin"]
