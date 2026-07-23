"""The Web-Research Orchestrator's output contract — an answer plus a citation graph.

Ported in spirit from eu-swarm's ``SmartScrapingOutput`` (the smart-scraper's 5-key
contract): the deliverable is not a landed artifact but a **return value** the spawning
employee consumes. The subagent's brief (see :mod:`._brief`) instructs it to emit exactly
this JSON as its final message; ``WebResearchOutput`` is the dream-free schema a caller can
validate that return against.

Every load-bearing claim in ``findings`` must reference sources in ``citation_graph`` — the
research analog of the scraper's "never finalize without a matching snippet": here, never a
claim without a citation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Source(BaseModel):
    """One cited source in the citation graph."""

    id: int = Field(description="Stable 1-based id referenced by findings and edges.")
    url: str = Field(description="The source URL that was read.")
    title: str = Field(default="", description="The source title, when available.")
    accessed: str | None = Field(
        default=None, description="ISO date the source was read, when available."
    )


class Finding(BaseModel):
    """One claim and the source ids that substantiate it."""

    claim: str = Field(description="A single, checkable statement.")
    sources: list[int] = Field(
        default_factory=list,
        description="Source ids substantiating the claim (aim for >= 2 independent).",
    )


class CitationEdge(BaseModel):
    """A claim -> source link in the citation graph."""

    claim_idx: int = Field(description="Index into ``findings``.")
    source_id: int = Field(description="Id of a source in ``citation_graph.sources``.")


class CitationGraph(BaseModel):
    """Sources and the claim->source edges that connect them."""

    sources: list[Source] = Field(default_factory=list)
    edges: list[CitationEdge] = Field(default_factory=list)


class QueryTrace(BaseModel):
    """One step of the replayable research trail: a query and the URLs it opened."""

    query: str = Field(description="A search query that was run.")
    opened: list[str] = Field(
        default_factory=list, description="URLs read (web_extract) off this query."
    )


class WebResearchOutput(BaseModel):
    """The Web-Research Orchestrator's return contract."""

    answer: str = Field(description="The synthesized answer to the research question.")
    findings: list[Finding] = Field(
        default_factory=list, description="Claims, each tied to its supporting sources."
    )
    citation_graph: CitationGraph = Field(
        default_factory=CitationGraph,
        description="Sources plus claim->source edges.",
    )
    assumptions: list[str] = Field(
        default_factory=list, description="What was inferred or could not be found."
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Confidence in the answer (0-1), calibrated to source agreement.",
    )
    trail: list[QueryTrace] = Field(
        default_factory=list, description="The queries run and URLs opened, for replay."
    )


def web_research_output_schema() -> dict[str, Any]:
    """The JSON schema for :class:`WebResearchOutput` (for spawn-time ``output_schema``)."""
    return WebResearchOutput.model_json_schema()


__all__ = [
    "CitationEdge",
    "CitationGraph",
    "Finding",
    "QueryTrace",
    "Source",
    "WebResearchOutput",
    "web_research_output_schema",
]
