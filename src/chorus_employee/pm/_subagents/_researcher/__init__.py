"""The Researcher — the PM's evidence specialist (pm design doc §06/§10).

A Tier-1 subagent Piper spawns mid-beat to answer ONE evidence question and hand back a typed, cited
:class:`ResearchBrief`. It is depth-2 — it dispatches the shared Web-Research Orchestrator so every
market/user claim carries a real citation rather than being written from memory, exactly as the
Marketer's Strategist does. It gathers evidence; it does not make the call — the PM owns the decision.

The return contract (:mod:`._schema`) is pydantic-authored and emitted to the spec's ``output_schema``
via :func:`research_output_schema`, so dream validates the child's final message at runtime and the PM
always gets a well-formed brief (with the ``source_url``\\ s that clear its grounding floor).
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec
from chorus_employee.pm._subagents._researcher._schema import (
    EvidenceItem,
    ResearchBrief,
    research_output_schema,
)
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR

RESEARCHER_SUBAGENT = SubagentSpec(
    name="researcher",
    description=(
        "You are the Researcher — the PM's evidence specialist. You answer ONE evidence question with "
        "real, cited facts and hand them back. You gather evidence; you do NOT decide what to build.\n\n"
        "## Your job\n"
        "1. Read the task brief and any existing material in your working directory with `read_file` "
        "to understand exactly what decision the evidence must inform.\n"
        "2. Ground every fact in REAL sources — do NOT write market/user/competitor claims from "
        "memory. Dispatch the `web_research` subagent EXACTLY ONCE: "
        '`spawn_subagent(name="web_research", prompt="<one focused question naming the ACTUAL '
        'product/market/metric>")`. It returns a cited JSON answer; every item in your EVIDENCE comes '
        "from it, with its source URL. One focused question is enough — do NOT spawn web_research again "
        "or fan out extra searches; three or four cited claims is plenty.\n"
        "3. Write `research_brief.md` — a tight, skimmable brief: the QUESTION, the EVIDENCE (each "
        "fact with its source URL and a confidence), the NEW ANGLE the evidence surfaced, the GAPS "
        "(what you could not verify), and LEARNINGS worth keeping.\n"
        "4. Return a JSON object matching your output contract: `brief_file` (the path you wrote, "
        "e.g. `research_brief.md`), `question`, `evidence` (a list where each item is a `claim`, its "
        "`source_url`, and a `confidence` 0..1), `new_angle`, `gaps`, and `learnings`. The file is the "
        "artifact; the JSON is the handoff the PM cites from.\n\n"
        "## Hard rules\n"
        "- Cite every claim with a `source_url` from `web_research` — never fabricate a URL. If you "
        "could not verify a point, leave `evidence` empty (or omit that point) and name it in `gaps`. "
        "An honest gap beats a made-up citation.\n"
        "- You do NOT decide or write the plan. You never write `plan.md`, never pick the bet, never "
        "state a `## Decision` — that is the PM's job. You hand over evidence; the PM makes the call.\n"
        "- Keep it to a page. A brief the PM won't read is a brief that failed."
    ),
    # Read to understand the ask, write the brief, and the web tools + spawn_subagent it delegates to
    # web_research (transitivity). All ⊆ the PM's shelf, so capability minimisation holds.
    tools=("read_file", "write_file", "web_search", "web_extract", "spawn_subagent"),
    # Depth-2: the Researcher dispatches the shared Web-Research Orchestrator for cited facts.
    spawnable=(WEB_RESEARCH_ORCHESTRATOR,),
    # Read the ask, spawn web_research ONCE, write the brief — 6 keeps the sweep short (a wider budget
    # let each Researcher run a long saturating sweep; a decision needs a few cited claims, not dozens).
    max_turns=6,
    # Runtime-enforced return contract: the typed ResearchBrief (artifact path + cited findings).
    output_schema=research_output_schema(),
)

__all__ = [
    "RESEARCHER_SUBAGENT",
    "EvidenceItem",
    "ResearchBrief",
    "research_output_schema",
]
