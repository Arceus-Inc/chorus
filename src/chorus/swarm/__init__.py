"""Shared swarm-role registry — reusable Tier-2 capability agents (spec GM §4, §13).

Net-new and role-agnostic: a registry of capability-minimized swarm roles (the Query Orchestrator)
that any employee's dream intra-task swarm can pull in, instead of redefining them per plugin. The
agentic twin of the shared tool registry — kernel-level, inherited by the whole workforce.
"""

from __future__ import annotations

from chorus.swarm._defaults import QUERY_ORCHESTRATOR, default_swarm_roles
from chorus.swarm._registry import SwarmRole, SwarmRoleRegistry

__all__ = [
    "QUERY_ORCHESTRATOR",
    "SwarmRole",
    "SwarmRoleRegistry",
    "default_swarm_roles",
]
