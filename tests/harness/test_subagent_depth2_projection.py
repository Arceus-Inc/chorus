"""Depth-2 projection: a chorus SubagentSpec.spawnable → dream Subagent.spawnable (design: bounded).

A Tier-1 spec may declare the Tier-2 specs it can itself dispatch. The factory projection carries
that nesting onto dream, mapping tool names and intersecting each grandchild with its parent spec's
tools (so the narrower-wins chain holds transitively).
"""

from __future__ import annotations

import pytest

from chorus.roles import RoleBeatConfig
from chorus.roles._subagent import SubagentSpec
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration


def _config_with(spec: SubagentSpec) -> RoleBeatConfig:
    return RoleBeatConfig(
        system_prompt="s",
        tools=("read_file", "browser_run", "spawn_subagent"),
        subagents=(spec,),
    )


class TestSpawnableProjection:
    def test_spec_spawnable_defaults_empty(self) -> None:
        spec = SubagentSpec(name="x", description="d", tools=("read_file",))
        assert spec.spawnable == ()

    def test_projection_is_role_agnostic(self) -> None:
        spec = SubagentSpec(
            name="arbitrary_writer",
            description="writes shared intent",
            tools=("read_file",),
        )
        subagent_set = _subagent_set(_config_with(spec))

        assert subagent_set is not None
        projected = subagent_set.get(spec.name)
        assert projected is not None

    def test_nested_spawnable_projected_onto_dream(self) -> None:
        researcher = SubagentSpec(
            name="web_research", description="reads the web", tools=("browser_run",)
        )
        strategist = SubagentSpec(
            name="strategist",
            description="frames the bet",
            # A spawner must itself hold what it delegates (transitivity): it grants web tools down.
            tools=("read_file", "browser_run", "spawn_subagent"),
            spawnable=(researcher,),
        )
        subagent_set = _subagent_set(_config_with(strategist))

        assert subagent_set is not None
        projected = subagent_set.get("strategist")
        assert projected is not None
        assert "spawn_subagent" in projected.tools
        assert [c.name for c in projected.spawnable] == ["web_research"]
        assert projected.spawnable[0].tools == ("browser_run",)

    def test_grandchild_intersected_with_parent_spec_tools(self) -> None:
        """A spawnable child can only narrow: its tools ∩ the spawner spec's tools."""
        greedy = SubagentSpec(
            name="web_research", description="d", tools=("browser_run", "run_command")
        )
        strategist = SubagentSpec(
            name="strategist",
            description="frames the bet",
            tools=("read_file", "browser_run", "spawn_subagent"),  # no run_command
            spawnable=(greedy,),
        )
        subagent_set = _subagent_set(_config_with(strategist))

        assert subagent_set is not None
        projected = subagent_set.get("strategist")
        assert projected is not None
        assert projected.spawnable[0].tools == ("browser_run",)  # run_command dropped


class TestMarketerLeanRoster:
    """Lean cut: brand_critic + web_research only (no strategist/creative middlemen)."""

    def test_marketer_keeps_isolation_earners_only(self) -> None:
        from chorus.roles import role_beat_config
        from chorus_employee.marketer import marketer_plugin

        config = role_beat_config(marketer_plugin().manifest)
        subagent_set = _subagent_set(config)

        assert subagent_set is not None
        assert set(subagent_set.names()) == {"brand_critic", "web_research"}
        assert subagent_set.get("strategist") is None
        web = subagent_set.get("web_research")
        assert web is not None
        assert web.spawnable == ()
