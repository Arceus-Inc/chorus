"""``WEB_RESEARCH_ORCHESTRATOR`` — the reusable web-research subagent declaration.

A single :class:`~chorus.roles.SubagentSpec` any employee can spawn to answer a research
question from the live web. It is capability-minimized: ``browser_run`` drives Chromium
(search, navigate, read rendered pages) for JS-heavy pages, and ``web_fetch`` is the cheap
no-browser read for simple pages — but it cannot write files or run shell. Its whole
operating contract lives in the brief.
"""

from __future__ import annotations

from chorus.roles._subagent import IsolationMode, SubagentSpec
from swarm.web_research_orchestrator._brief import _WEB_RESEARCH_BRIEF
from swarm.web_research_orchestrator._schemas import web_research_output_schema

# Kept as a module constant so the opt-in helper can guarantee the parent grants a superset
# (narrower-wins would otherwise strip them).
WEB_RESEARCH_SUBAGENT_TOOLS: tuple[str, ...] = ("browser_run", "web_fetch")

WEB_RESEARCH_ORCHESTRATOR = SubagentSpec(
    name="web_research",
    description=_WEB_RESEARCH_BRIEF,
    tools=WEB_RESEARCH_SUBAGENT_TOOLS,
    # Research is turn-hungry: navigate→read→cross-check per sub-question. 10 keeps a focused
    # sweep within a parent beat while still allowing real triangulation.
    max_turns=10,
    # Runtime-enforced return contract: the brief instructs the JSON shape (soft); this makes it hard
    # — the inline executor validates + repair-loops + fails open with a warning (WebResearchOutput).
    output_schema=web_research_output_schema(),
    # Noise isolation: research fetches belong in an ephemeral worktree (Dream PR #111).
    isolation=IsolationMode.WORKTREE,
)

__all__ = ["WEB_RESEARCH_ORCHESTRATOR", "WEB_RESEARCH_SUBAGENT_TOOLS"]
