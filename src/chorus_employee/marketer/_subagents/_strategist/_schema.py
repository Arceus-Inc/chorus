"""The Strategist subagent's typed return contract (design doc §06, §10).

After the Strategist frames the bet, it writes ``strategy_brief.md`` AND returns a
:class:`StrategyBrief` — the artifact path plus the structured bet (hypothesis, audience,
channel, message angle, success metric) and the :class:`EvidenceItem` facts behind it, each
carrying the ``web_research`` citation that grounds it. The Creative drafts straight from this.

Pydantic models are the single source of truth: :func:`strategy_output_schema` *derives* the JSON
schema the subagent's ``output_schema`` enforces via :meth:`~pydantic.BaseModel.model_json_schema`
(dream's ``jsonschema`` validator resolves its ``$ref``/``$defs``), and a caller parses the raw
return with :meth:`StrategyBrief.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """One cited market fact behind the bet — a claim and the source that grounds it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    claim: str = Field(min_length=1, description="a market fact behind the bet, stated plainly")
    source: str = Field(
        min_length=1,
        description="the web_research citation for this claim (URL or source title)",
    )


class StrategyBrief(BaseModel):
    """Strategist's return value: the artifact it wrote plus the structured, grounded bet."""

    model_config = ConfigDict(str_strip_whitespace=True)

    brief_file: str = Field(
        min_length=1,
        description="worktree-relative path Strategist wrote the brief to, e.g. strategy_brief.md",
    )
    hypothesis: str = Field(
        min_length=1,
        description="the bet in one sentence ('we believe X audience will Y because Z')",
    )
    audience: str = Field(
        min_length=1, description="who, and the one insight about them that matters"
    )
    channel: str = Field(min_length=1, description="channel + format and why that surface fits")
    message_angle: str = Field(
        min_length=1, description="the single most important thing to say (problem-first)"
    )
    success_metric: str = Field(
        min_length=1, description="the metric that moves and what 'good' looks like"
    )
    evidence: list[EvidenceItem] = Field(
        description="the cited facts behind the bet (from web_research), each with its source"
    )


def strategy_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Strategist subagent's ``output_schema`` — derived from the model."""
    return StrategyBrief.model_json_schema()


__all__ = ["EvidenceItem", "StrategyBrief", "strategy_output_schema"]
