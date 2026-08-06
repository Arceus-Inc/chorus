"""Web-Research Orchestrator — a shared, reusable subagent for evidence-grounded web research.

One :class:`~chorus.roles.SubagentSpec` any employee can spawn to answer a research question from
the live web using ``browser_run`` (Chromium CDP via browser-harness). It plans a multi-source
sweep, opens pages in a real browser, cross-checks claims, and returns a structured answer with a
citation graph (:class:`WebResearchOutput`).

- :data:`WEB_RESEARCH_ORCHESTRATOR` — the subagent declaration (brief, tools, turn budget).
- :func:`with_web_research` — splice it (and the tools it needs) into any role's manifest.
- :class:`WebResearchOutput` — the return contract a caller can validate the subagent against.
"""

from __future__ import annotations

from swarm.web_research_orchestrator._optin import WEB_RESEARCH_TOOLS, with_web_research
from swarm.web_research_orchestrator._schemas import (
    CitationEdge,
    CitationGraph,
    Finding,
    QueryTrace,
    Source,
    WebResearchOutput,
    web_research_output_schema,
)
from swarm.web_research_orchestrator._subagent import (
    WEB_RESEARCH_ORCHESTRATOR,
    WEB_RESEARCH_SUBAGENT_TOOLS,
)

__all__ = [
    "WEB_RESEARCH_ORCHESTRATOR",
    "WEB_RESEARCH_SUBAGENT_TOOLS",
    "WEB_RESEARCH_TOOLS",
    "CitationEdge",
    "CitationGraph",
    "Finding",
    "QueryTrace",
    "Source",
    "WebResearchOutput",
    "web_research_output_schema",
    "with_web_research",
]
