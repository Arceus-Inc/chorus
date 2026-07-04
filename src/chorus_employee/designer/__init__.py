"""The Designer — the fidelity role that turns intent into an interface, under a gate (designer §01-§16).

One employee = one configured dream harness. This package gathers *everything* that makes a Designer that
harness, one component per module:

- :mod:`._brief`    — the operating brief (system prompt) + the design-system + design-spec filenames.
- :mod:`._harness`  — the :class:`~chorus.roles.RoleManifest`: every ``build_harness`` component.
- :mod:`._dod`      — the Definition of Done (intent -> typed :class:`~chorus.outcomes.Verifier`).
- :mod:`._lander`   — the ``design`` :class:`~chorus.outcomes.OutcomeLander` (committed spec).
- :mod:`._routines` — standing routines (system-drift scan, accessibility audit — later slice).
- :mod:`._subagents` — Tier-1 subagents (Explorer, Design-Critic, UX-Researcher).

:func:`designer_plugin` assembles the role triple; :func:`designer_lander` provides the matching
:class:`~chorus.outcomes.OutcomeLander`. This is the **single source** of the Designer:
``chorus.roles.default_roles`` imports the plugin from here rather than re-declaring it.

The Designer is the Marketer's structural twin (designer §02): brand → design system, ``brand_lint`` →
``design_lint``, Brand-Critic → Design-Critic, Creative → Explorer, go-live → handoff. Reuse over invention.
"""

from __future__ import annotations

from chorus.roles._plugin import RolePlugin
from chorus_employee.designer._brief import (
    DESIGN_SPEC_DOC,
    DESIGN_SYSTEM_DOC,
    DESIGNER_BRIEF,
)
from chorus_employee.designer._dod import designer_dod
from chorus_employee.designer._harness import designer_manifest
from chorus_employee.designer._lander import DesignerLander, designer_lander
from chorus_employee.designer._routines import DESIGNER_ROUTINES
from chorus_employee.designer._subagents import (
    DESIGN_CRITIC_SUBAGENT,
    EXPLORER_SUBAGENT,
    UX_RESEARCHER_SUBAGENT,
    DesignVerdict,
    DesignViolation,
    EvidenceItem,
    ExplorerManifest,
    UxBrief,
    VariantEntry,
    design_verdict_output_schema,
    explorer_output_schema,
    ux_brief_output_schema,
)


def designer_plugin() -> RolePlugin:
    """The registrable Designer role — manifest + DoD + outcome kind (designer §02)."""
    return RolePlugin(
        name="designer",
        manifest=designer_manifest(),
        dod_generator=designer_dod,
        outcome_kind="design",
        declared_routines=DESIGNER_ROUTINES,
    )


__all__ = [
    "DESIGNER_BRIEF",
    "DESIGNER_ROUTINES",
    "DESIGN_CRITIC_SUBAGENT",
    "DESIGN_SPEC_DOC",
    "DESIGN_SYSTEM_DOC",
    "EXPLORER_SUBAGENT",
    "UX_RESEARCHER_SUBAGENT",
    "DesignVerdict",
    "DesignViolation",
    "DesignerLander",
    "EvidenceItem",
    "ExplorerManifest",
    "UxBrief",
    "VariantEntry",
    "design_verdict_output_schema",
    "designer_dod",
    "designer_lander",
    "designer_manifest",
    "designer_plugin",
    "explorer_output_schema",
    "ux_brief_output_schema",
]
