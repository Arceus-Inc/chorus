"""The Frontend Engineer — the role that turns intent into a working, tested interface.

One employee = one configured dream harness. This package gathers *everything* that makes a Frontend
Engineer that harness, one component per module:

- :mod:`._brief`    — the operating brief (system prompt) + the deliverable/evidence filename contract.
- :mod:`._harness`  — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`      — the Definition of Done (intent -> typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._routines` — standing routines (none yet — it acts on assigned tasks).

:func:`frontend_engineer_plugin` assembles the role triple. Its outcome kind is ``pr`` — it lands
running code — so it reuses the Engineer's registered ``pr`` :class:`~chorus.outcomes.OutcomeLander`
(``chorus_employee.default_landers``) rather than declaring its own. This is the **single source** of the
Frontend Engineer: ``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.

The Frontend Engineer is the Designer's structural sibling (spec/build split): the Designer writes a
``design_spec.md`` and runs nothing; the Frontend Engineer builds the running app, RUNS its tests, and
lands a durable ``test_evidence/`` bundle — ``design_lint`` → ``test_evidence``, the Design-Critic →
the UI-Tester + Code-Reviewer.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.frontend_engineer._brief import (
    E2E_TEST_LOG,
    FRONTEND_ENGINEER_BRIEF,
    TEST_EVIDENCE_DIR,
    TEST_EVIDENCE_SUMMARY,
    UNIT_TEST_LOG,
)
from chorus_employee.frontend_engineer._dod import frontend_engineer_dod
from chorus_employee.frontend_engineer._harness import frontend_engineer_manifest
from chorus_employee.frontend_engineer._routines import FRONTEND_ENGINEER_ROUTINES


def frontend_engineer_plugin() -> RolePlugin:
    """The registrable Frontend Engineer role — manifest + DoD + outcome kind (``pr``)."""
    return RolePlugin(
        name="frontend_engineer",
        manifest=frontend_engineer_manifest(),
        dod_generator=frontend_engineer_dod,
        outcome_kind="pr",  # lands running code — reuses the Engineer's `pr` lander
        declared_routines=FRONTEND_ENGINEER_ROUTINES,
    )


__all__ = [
    "E2E_TEST_LOG",
    "FRONTEND_ENGINEER_BRIEF",
    "FRONTEND_ENGINEER_ROUTINES",
    "TEST_EVIDENCE_DIR",
    "TEST_EVIDENCE_SUMMARY",
    "UNIT_TEST_LOG",
    "frontend_engineer_dod",
    "frontend_engineer_manifest",
    "frontend_engineer_plugin",
]
