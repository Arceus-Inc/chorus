"""Designer subagents — the UX-Researcher, Design-Critic, and Explorer (designer §06, §10).

Three Tier-1, role-owned specialists the Designer spawns mid-beat — the structural twins of the
Marketer's Strategist, Brand-Critic, and Creative. Each is its own subpackage: the ``__init__``
carries the :class:`~chorus.roles.SubagentSpec` and its sibling ``_schema`` module holds the
pydantic-authored return contract, emitted to the spec's ``output_schema`` so dream validates the
child's final message at runtime.

- **UX-Researcher** (:mod:`._ux_researcher`) — frames the grounded design bet *before* exploring: a
  web-research-grounded approach and flow plan the Explorer designs from. Depth-2 (spawns
  web_research). Returns a :class:`~...._ux_researcher.UxBrief`.
- **Design-Critic** (:mod:`._design_critic`) — a read-only adversarial reviewer (the "post-gen"
  layer of the §10 validation sandwich) that checks a spec against the DESIGN.md system and its
  accessibility floor. Returns a :class:`~...._design_critic.DesignVerdict`.
- **Explorer** (:mod:`._explorer`) — a variation engine that drafts on-system variants of a seed,
  self-lints each, and returns an :class:`~...._explorer.ExplorerManifest`. It varies *layout and
  interaction*, never *the token system*.

Tier-1, role-owned. Each spec's ``tools`` are CHORUS names (mapped to dream + intersected with the
Designer's toolset at materialize). Each spawned child's system prompt is generated from name +
description, so the full brief lives *in* the description — imperative, so the specialist actually
reads the files and produces its deliverable rather than claiming it cannot.
"""

from __future__ import annotations

from chorus_employee.designer._subagents._design_critic import (
    DESIGN_CRITIC_SUBAGENT,
    DesignVerdict,
    DesignViolation,
    design_verdict_output_schema,
)
from chorus_employee.designer._subagents._explorer import (
    EXPLORER_SUBAGENT,
    ExplorerManifest,
    VariantEntry,
    explorer_output_schema,
)
from chorus_employee.designer._subagents._ux_researcher import (
    UX_RESEARCHER_SUBAGENT,
    EvidenceItem,
    UxBrief,
    ux_brief_output_schema,
)

__all__ = [
    "DESIGN_CRITIC_SUBAGENT",
    "EXPLORER_SUBAGENT",
    "UX_RESEARCHER_SUBAGENT",
    "DesignVerdict",
    "DesignViolation",
    "EvidenceItem",
    "ExplorerManifest",
    "UxBrief",
    "VariantEntry",
    "design_verdict_output_schema",
    "explorer_output_schema",
    "ux_brief_output_schema",
]
