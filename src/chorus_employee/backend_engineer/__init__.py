"""The Backend Engineer — a service a stranger can depend on, proven and landed (spec §02, §16 Slice 1).

The Engineer's structural twin: it consumes a ticket + contract, builds and runs the service in an
isolated worktree, and lands a reviewed ``pr``. This package gathers everything that makes it that
dream harness, one component per module — mirroring ``chorus_employee/engineer/``:

- :mod:`._brief`   — the operating brief (system prompt).
- :mod:`._harness` — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`     — the Definition of Done (intent → a reviewed-build :class:`~chorus.outcomes.Verifier`).

Its outcome kind is ``pr`` — the same as the Engineer's — so the Engineer's ``pr`` lander already
handles its landing (the :class:`~chorus.outcomes.LanderRegistry` keys on ``outcome_kind``, not role);
no new lander is needed for the walking skeleton. :func:`backend_engineer_plugin` assembles the triple;
``chorus.roles.default_roles`` imports it from here (single source — no drift).
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.backend_engineer._brief import BACKEND_ENGINEER_BRIEF
from chorus_employee.backend_engineer._dod import backend_engineer_dod
from chorus_employee.backend_engineer._harness import backend_engineer_manifest
from chorus_employee.backend_engineer._subagents import (
    API_VERIFIER_SUBAGENT,
    ApiCheck,
    ApiTestVerdict,
    api_test_verdict_output_schema,
)


def backend_engineer_plugin() -> RolePlugin:
    """The registrable Backend Engineer role — manifest + DoD + outcome kind (spec 06 §2)."""
    return RolePlugin(
        name="backend_engineer",
        manifest=backend_engineer_manifest(),
        dod_generator=backend_engineer_dod,
        outcome_kind="pr",
    )


__all__ = [
    "API_VERIFIER_SUBAGENT",
    "BACKEND_ENGINEER_BRIEF",
    "ApiCheck",
    "ApiTestVerdict",
    "api_test_verdict_output_schema",
    "backend_engineer_dod",
    "backend_engineer_manifest",
    "backend_engineer_plugin",
]
