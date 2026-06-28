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


def default_swarm_roles() -> tuple[SwarmRole, ...]:
    """The canonical shared swarm roles, registered at boot (spec GM §4)."""
    return (QUERY_ORCHESTRATOR,)


__all__ = ["QUERY_ORCHESTRATOR", "default_swarm_roles"]
