"""Marketer subagents — the Strategist, Brand-Critic, and Creative/Copywriter (design doc §06, §10).

Three Tier-1, role-owned specialists Mira spawns mid-beat. Each is its own subpackage: the
``__init__`` carries the :class:`~chorus.roles.SubagentSpec` and its sibling ``_schema`` module
holds the pydantic-authored return contract, emitted to the spec's ``output_schema`` so dream
validates the child's final message at runtime.

- **Strategist** (:mod:`._strategist`) — frames the grounded bet *before* drafting: a
  web-research-grounded hypothesis and channel plan the Creative drafts from. Depth-2 (spawns
  web_research). Returns a :class:`~...._strategist.StrategyBrief`.
- **Brand-Critic** (:mod:`._brand_critic`) — a read-only adversarial reviewer (the "post-gen"
  layer of the §10 validation sandwich) that checks a draft against the voice spec. Returns a
  :class:`~...._brand_critic.BrandVerdict`.
- **Creative/Copywriter** (:mod:`._creative`) — a variation engine that drafts on-brand variants
  of a grounded seed, self-lints each, and returns a :class:`~...._creative.CreativeManifest`. It
  varies *expression*, never *evidence*.

Tier-1, role-owned. Each spec's ``tools`` are CHORUS names (mapped to dream + intersected with the
marketer's toolset at materialize). Each spawned child's system prompt is generated from name +
description, so the full brief lives *in* the description — imperative, so the specialist actually
reads the files and produces its deliverable rather than claiming it cannot.
"""

from __future__ import annotations

from chorus_employee.marketer._subagents._brand_critic import (
    BRAND_CRITIC_SUBAGENT,
    BrandVerdict,
    Violation,
    brand_verdict_output_schema,
)
from chorus_employee.marketer._subagents._creative import (
    CREATIVE_SUBAGENT,
    CreativeManifest,
    VariantEntry,
    creative_output_schema,
)
from chorus_employee.marketer._subagents._strategist import (
    STRATEGIST_SUBAGENT,
    EvidenceItem,
    StrategyBrief,
    strategy_output_schema,
)

__all__ = [
    "BRAND_CRITIC_SUBAGENT",
    "CREATIVE_SUBAGENT",
    "STRATEGIST_SUBAGENT",
    "BrandVerdict",
    "CreativeManifest",
    "EvidenceItem",
    "StrategyBrief",
    "VariantEntry",
    "Violation",
    "brand_verdict_output_schema",
    "creative_output_schema",
    "strategy_output_schema",
]
