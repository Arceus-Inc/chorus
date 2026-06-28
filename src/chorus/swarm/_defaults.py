"""The shared Tier-2 capability agents registered at boot (spec GM §4).

These are role-agnostic — the Segment, Experiment, and Monitor specialists of *any* data-needing
employee delegate to the same Query Orchestrator. A consumer adds another shared agent with
``SwarmRoleRegistry.register(...)`` — never by editing a role plugin.
"""

from __future__ import annotations

from chorus.swarm._registry import SwarmRole

# The reusable data-reasoning agent: takes a question, plans which sources to hit, writes the SQL,
# runs it across warehouse + analytics, iterates when a query returns junk, and returns an answer.
# Its deterministic primitives stay tools underneath it; "query patterns" is the know-how it reads.
QUERY_ORCHESTRATOR = SwarmRole(
    name="query_orchestrator",
    description=(
        "Takes a data question, plans which sources to hit, writes and runs the query across "
        "warehouse + analytics, iterates when a query returns junk, and returns an answer."
    ),
    tools=("warehouse.query", "analytics.fetch"),
    skills=("query_patterns",),
    spawned_by=("segment", "experiment", "monitor"),
)

# The lead-hunting twin of the query orchestrator: instead of internal data it reasons over the open
# web. It takes a go-to-market play, generates angled search strategies, expands each into a
# broad/intent/icp query grid across Google/LinkedIn/X/Reddit, reads each query's health
# (ghost-town vs haystack), heals the weak ones, classifies results into real buyer leads, and keeps
# expanding until the sweep saturates. Its deterministic scaffolding (query health, dedupe,
# exhaustiveness) lives in :mod:`chorus.webplugins._search`; the judgment is the agent's.
LEAD_ORCHESTRATOR = SwarmRole(
    name="lead_orchestrator",
    description=(
        "Takes a go-to-market play, generates angled search strategies, expands them into a "
        "multi-platform query grid, probes each query and heals the weak ones, then classifies and "
        "dedupes the results into real buyer leads until the sweep saturates."
    ),
    tools=("search.google", "search.linkedin", "search.twitter", "leads.classify"),
    skills=("play_strategies", "boolean_query_syntax"),
    spawned_by=("prospector",),
)


def default_swarm_roles() -> tuple[SwarmRole, ...]:
    """The canonical shared swarm roles, registered at boot (spec GM §4)."""
    return (QUERY_ORCHESTRATOR, LEAD_ORCHESTRATOR)


__all__ = ["LEAD_ORCHESTRATOR", "QUERY_ORCHESTRATOR", "default_swarm_roles"]
