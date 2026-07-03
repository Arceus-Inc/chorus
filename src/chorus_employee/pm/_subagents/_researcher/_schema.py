"""The Researcher subagent's typed return contract (pm design doc §06/§10).

After the Researcher runs its evidence sweep it writes ``research_brief.md`` AND returns a
:class:`ResearchBrief` — the artifact path plus the structured findings: the :class:`EvidenceItem`
facts (each a claim, its ``source_url`` citation, and a bounded confidence), the ``new_angle`` the
evidence surfaced, the honest ``gaps``, and a durable ``learnings`` note for the skill base (the §06
three-part contract: feedback/new-angle/learnings). The PM drops the ``source_url``\\ s straight into
its plan's ``## Decision`` — which is what clears the grounding-floor DoD.

Pydantic models are the single source of truth: :func:`research_output_schema` *derives* the JSON
schema the subagent's ``output_schema`` enforces via :meth:`~pydantic.BaseModel.model_json_schema`
(dream's ``jsonschema`` validator resolves its ``$ref``/``$defs``), and a caller parses the raw return
with :meth:`ResearchBrief.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """One cited finding — a claim, the source that grounds it, and how strongly it does."""

    model_config = ConfigDict(str_strip_whitespace=True)

    claim: str = Field(min_length=1, description="a market/user fact relevant to the decision")
    source_url: str = Field(
        min_length=1,
        description="the citation that grounds this claim (a URL from web_research) — the PM drops "
        "this into its plan's ## Decision, so it must be a real, reachable source",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="0..1 — how strongly the source supports the claim (0.5 = suggestive, 0.9 = "
        "direct primary evidence)",
    )


class ResearchBrief(BaseModel):
    """The Researcher's return value: the artifact it wrote plus the structured, cited findings."""

    model_config = ConfigDict(str_strip_whitespace=True)

    brief_file: str = Field(
        min_length=1,
        description="worktree-relative path the Researcher wrote, e.g. research_brief.md",
    )
    question: str = Field(
        min_length=1, description="the evidence question the Researcher set out to answer"
    )
    evidence: list[EvidenceItem] = Field(
        description="cited findings, each a claim + source_url + confidence; empty ONLY when nothing "
        "could be verified — never a fabricated citation (name the gap in `gaps` instead)"
    )
    new_angle: str = Field(
        min_length=1,
        description="a problem perspective the evidence surfaced that the PM should validate — the "
        "'new angle' half of the §06 subagent contract",
    )
    gaps: str = Field(
        min_length=1,
        description="what remains unknown or could not be verified — honest about the edge of the "
        "evidence, so the PM doesn't over-state confidence",
    )
    learnings: str = Field(
        min_length=1,
        description="a durable insight worth keeping for future decisions — the 'learnings' half of "
        "the §06 contract (feeds the skill base)",
    )


def research_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Researcher subagent's ``output_schema`` — derived from the model."""
    return ResearchBrief.model_json_schema()


__all__ = ["EvidenceItem", "ResearchBrief", "research_output_schema"]
