"""Marketer subagents — lean isolation earners Mira spawns mid-beat.

The Brand-Critic is the retained Tier-1 specialist: a read-only adversarial review
of a draft against the voice spec. Framing and variety live as skills
(``channel-priors``, ``brand-voice``) plus ``web_research`` on the main employee.

Typed strategist/creative schemas remain available for tests; they are not
spawnable roster entries.
"""

from __future__ import annotations

from chorus_employee.marketer._subagents._brand_critic import (
    BRAND_CRITIC_SUBAGENT,
    BrandVerdict,
    Violation,
    brand_verdict_output_schema,
)
from chorus_employee.marketer._subagents._creative import (
    CreativeManifest,
    VariantEntry,
    creative_output_schema,
)
from chorus_employee.marketer._subagents._strategist import (
    EvidenceItem,
    StrategyBrief,
    strategy_output_schema,
)

__all__ = [
    "BRAND_CRITIC_SUBAGENT",
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
