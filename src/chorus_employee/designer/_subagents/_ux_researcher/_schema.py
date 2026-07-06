"""The UX-Researcher subagent's typed return contract (designer §06, §10).

After the UX-Researcher frames the design bet, it writes ``ux_brief.md`` AND returns a
:class:`UxBrief` — the artifact path plus the structured approach (user needs, key flows,
accessibility targets, the patterns it recommends) and the :class:`EvidenceItem` facts behind it,
each carrying the ``web_research`` citation that grounds it. The Explorer and Designer draft
straight from this.

Pydantic models are the single source of truth (mirroring the Strategist's contract):
:func:`ux_brief_output_schema` *derives* the JSON schema the subagent's ``output_schema`` enforces
via :meth:`~pydantic.BaseModel.model_json_schema` (dream's ``jsonschema`` validator resolves its
``$ref``/``$defs``), and a caller parses the raw return with :meth:`UxBrief.model_validate` — no
hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EvidenceItem(BaseModel):
    """One cited UX fact behind the approach — a claim and the source that grounds it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    claim: str = Field(
        min_length=1,
        description="a UX/pattern/accessibility fact behind the approach, stated plainly",
    )
    source: str = Field(
        min_length=1,
        description="the web_research citation for this claim (URL or source title)",
    )


class UxBrief(BaseModel):
    """UX-Researcher's return value: the artifact it wrote plus the structured, grounded approach."""

    model_config = ConfigDict(str_strip_whitespace=True)

    brief_file: str = Field(
        min_length=1,
        description="worktree-relative path UX-Researcher wrote the brief to, e.g. ux_brief.md",
    )
    approach: str = Field(
        min_length=1,
        description="the recommended design approach in one sentence ('users need X, so lead with Y')",
    )
    user_needs: str = Field(
        min_length=1, description="who the surface serves and the one need that matters most"
    )
    key_flows: str = Field(
        min_length=1, description="the primary user flow(s) the surface must make effortless"
    )
    accessibility_targets: str = Field(
        min_length=1,
        description="the concrete a11y targets (contrast ratio, keyboard path, focus order) to hold",
    )
    patterns: list[str] = Field(
        description="the interaction/layout patterns recommended, each grounded in evidence"
    )
    evidence: list[EvidenceItem] = Field(
        description="the cited facts behind the approach (from web_research), each with its source"
    )


def ux_brief_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the UX-Researcher's ``output_schema`` — derived from the model."""
    return UxBrief.model_json_schema()


__all__ = ["EvidenceItem", "UxBrief", "ux_brief_output_schema"]
