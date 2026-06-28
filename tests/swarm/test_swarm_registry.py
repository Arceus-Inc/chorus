"""SwarmRoleRegistry — fail-closed + idempotent shared Tier-2 capability agents (spec GM §4)."""

from __future__ import annotations

import pytest

from chorus.errors import SwarmRoleConflict, SwarmRoleInvalid
from chorus.swarm import (
    LEAD_ORCHESTRATOR,
    QUERY_ORCHESTRATOR,
    SwarmRole,
    SwarmRoleRegistry,
    default_swarm_roles,
)

pytestmark = pytest.mark.unit


def test_default_registry_holds_the_query_orchestrator() -> None:
    reg = SwarmRoleRegistry.from_roles(default_swarm_roles())
    assert "query_orchestrator" in reg
    role = reg.get("query_orchestrator")
    assert role.tools == ("warehouse.query", "analytics.fetch")
    assert "query_patterns" in role.skills
    assert set(role.spawned_by) == {"segment", "experiment", "monitor"}


def test_default_registry_holds_the_lead_orchestrator() -> None:
    reg = SwarmRoleRegistry.from_roles(default_swarm_roles())
    assert "lead_orchestrator" in reg
    role = reg.get("lead_orchestrator")
    # role-agnostic open-web prospecting twin of the query orchestrator.
    assert role is LEAD_ORCHESTRATOR
    assert "search.google" in role.tools and "leads.classify" in role.tools
    assert "play_strategies" in role.skills
    assert set(role.spawned_by) == {"prospector"}


def test_re_registering_an_identical_role_is_idempotent() -> None:
    reg = SwarmRoleRegistry()
    reg.register(QUERY_ORCHESTRATOR)
    reg.register(QUERY_ORCHESTRATOR)  # no raise
    assert len(reg) == 1


def test_conflicting_role_raises_without_replace() -> None:
    reg = SwarmRoleRegistry.from_roles(default_swarm_roles())
    other = SwarmRole(
        name="query_orchestrator",
        description="a different definition",
        tools=("warehouse.query",),
    )
    with pytest.raises(SwarmRoleConflict):
        reg.register(other)
    reg.register(other, replace=True)
    assert reg.get("query_orchestrator").description == "a different definition"


def test_a_role_must_declare_at_least_one_tool() -> None:
    with pytest.raises(SwarmRoleInvalid):
        SwarmRoleRegistry().register(SwarmRole(name="empty", description="no tools", tools=()))


def test_a_role_must_carry_a_description() -> None:
    with pytest.raises(SwarmRoleInvalid):
        SwarmRoleRegistry().register(SwarmRole(name="x", description="  ", tools=("t",)))


def test_an_empty_name_is_rejected() -> None:
    with pytest.raises(SwarmRoleInvalid):
        SwarmRoleRegistry().register(SwarmRole(name=" ", description="d", tools=("t",)))
