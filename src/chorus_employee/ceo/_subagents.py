"""The CEO's Tier-1 subagents — bounded specialists it can dispatch mid-beat.

Each is a capability-minimized teammate the CEO spawns with dream's ``spawn_subagent`` tool while
working a single governance/decision beat. Every subagent's tools are a **subset** of the CEO's own
toolset (the composition root intersects them at materialize), so a specialist can only narrow what the
CEO can do, never widen it. They are ephemeral: focused work, return text, dissolve — no recursion.
"""

from __future__ import annotations

from chorus.roles._subagent import SubagentSpec

CEO_SUBAGENTS: tuple[SubagentSpec, ...] = (
    SubagentSpec(
        name="advisor",
        description=(
            "Red-team the CEO's draft decision. You work in the CEO's working directory: read the "
            "company state and the draft directive, then challenge it hard — where is the evidence "
            "thin, what is the strongest case AGAINST the call, what downside is being ignored, and "
            "what would have to be true for this to fail. Return the specific weaknesses and the risks "
            "that most deserve a guardrail. Do not rewrite the decision — pressure-test it."
        ),
        tools=("read_file", "read_offloaded", "web_search", "web_extract"),
    ),
    SubagentSpec(
        name="researcher",
        description=(
            "Gather the external context the CEO's decision needs. You work in the CEO's working "
            "directory: use `web_search` to find current, credible sources and `web_extract` to read "
            "one in full. Return the concrete facts with their exact source URLs — market size, "
            "competitor moves, benchmarks, regulatory constraints — not opinion."
        ),
        tools=("web_search", "web_extract", "read_file", "read_offloaded"),
    ),
)

__all__ = ["CEO_SUBAGENTS"]
