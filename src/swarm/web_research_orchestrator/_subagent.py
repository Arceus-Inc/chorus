"""``WEB_RESEARCH_ORCHESTRATOR`` — the reusable web-research subagent declaration.

A single :class:`~chorus.roles.SubagentSpec` any employee can spawn to answer a research
question from the live web. It is capability-minimized to exactly two tools — ``web_search``
(discovery) and ``web_extract`` (fetch + clean read) — so it can read and cite the open web but
can neither write files, run commands, nor drive a browser. Its whole operating contract (the
policy, the saturation ladder, the triangulation rule, and the JSON output shape) lives in the
brief, because ``SubagentSpec`` generates the child's system prompt from name + description.

"Shared" by reuse, not by a tier-2 registry (chorus projects only Tier-1 subagents today): a role
opts in by splicing this spec into its manifest via :func:`._optin.with_web_research`.
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec
from swarm.web_research_orchestrator._brief import _WEB_RESEARCH_BRIEF

# The subagent's tools — the ONLY two it may use. Kept as a module constant so the opt-in helper
# can guarantee the parent grants a superset (narrower-wins would otherwise strip them).
WEB_RESEARCH_SUBAGENT_TOOLS: tuple[str, ...] = ("web_search", "web_extract")

WEB_RESEARCH_ORCHESTRATOR = SubagentSpec(
    name="web_research",
    description=_WEB_RESEARCH_BRIEF,
    tools=WEB_RESEARCH_SUBAGENT_TOOLS,
    # Research is turn-hungry: 2-5 sub-questions, each a search->extract->cross-check cycle, plus
    # the saturation ladder. 16 leaves room for a real sweep without running unbounded.
    max_turns=16,
)

__all__ = ["WEB_RESEARCH_ORCHESTRATOR", "WEB_RESEARCH_SUBAGENT_TOOLS"]
