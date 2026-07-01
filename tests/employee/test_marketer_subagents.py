"""Marketer — Slice 1: Brand-Critic subagent declaration and factory wiring (design doc §06, §10)."""

from __future__ import annotations

import pytest

from chorus.roles import RoleBeatConfig, role_beat_config
from chorus.roles._subagent import SubagentSpec
from chorus_employee.marketer import BRAND_CRITIC_SUBAGENT, marketer_plugin
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration


# --- Brand-Critic declaration ---


class TestBrandCriticDeclaration:
    def test_subagent_name(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.name == "brand_critic"

    def test_subagent_is_read_only(self) -> None:
        assert "write_file" not in BRAND_CRITIC_SUBAGENT.tools
        assert "run_command" not in BRAND_CRITIC_SUBAGENT.tools
        assert "read_file" in BRAND_CRITIC_SUBAGENT.tools

    def test_subagent_max_turns_bounded(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.max_turns <= 6

    def test_subagent_description_mentions_brand_voice(self) -> None:
        # The child's system prompt is generated from the description, so the full brief lives there.
        desc = BRAND_CRITIC_SUBAGENT.description.lower()
        assert "brand" in desc
        assert "voice" in desc

    def test_description_instructs_pass_fail_verdict(self) -> None:
        desc = BRAND_CRITIC_SUBAGENT.description
        assert "PASS" in desc
        assert "FAIL" in desc

    def test_description_instructs_read_only(self) -> None:
        desc = BRAND_CRITIC_SUBAGENT.description.lower()
        assert "read-only" in desc or "read only" in desc


# --- Manifest integration ---


class TestMarketerManifestSubagents:
    def test_manifest_declares_brand_critic(self) -> None:
        plugin = marketer_plugin()
        assert len(plugin.manifest.subagents) == 1
        assert plugin.manifest.subagents[0].name == "brand_critic"

    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        plugin = marketer_plugin()
        assert "spawn_subagent" in plugin.manifest.tools

    def test_subagent_tools_are_subset_of_parent_tools(self) -> None:
        plugin = marketer_plugin()
        parent_tools = set(plugin.manifest.tools)
        for subagent in plugin.manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in parent's tools — "
                    f"narrower-wins violation"
                )

    def test_beat_config_carries_the_subagents(self) -> None:
        config = role_beat_config(marketer_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {"brand_critic"}


# --- Factory projection ---


def _config(tools: tuple[str, ...], subagents: tuple[SubagentSpec, ...]) -> RoleBeatConfig:
    return RoleBeatConfig(system_prompt="x", tools=tools, subagents=subagents)


class TestProjectSubagents:
    def test_no_subagents_returns_none(self) -> None:
        assert _subagent_set(_config(("read_file",), ())) is None

    def test_single_subagent_projects_to_subagent_set(self) -> None:
        spec = SubagentSpec(
            name="test_agent",
            description="A test subagent",
            tools=("read_file",),
            max_turns=3,
        )
        result = _subagent_set(_config(("read_file",), (spec,)))
        assert result is not None
        assert "test_agent" in result
        assert len(result) == 1

    def test_projected_subagent_preserves_fields(self) -> None:
        spec = SubagentSpec(
            name="critic",
            description="Reviews things",
            tools=("read_file",),
            max_turns=4,
        )
        result = _subagent_set(_config(("read_file",), (spec,)))
        assert result is not None
        agent = result.get("critic")
        assert agent is not None
        assert agent.name == "critic"
        assert agent.description == "Reviews things"
        assert agent.max_turns == 4

    def test_projected_tools_are_dream_names(self) -> None:
        spec = SubagentSpec(
            name="runner",
            description="Runs commands",
            tools=("read_file", "run_command"),
            max_turns=2,
        )
        # The parent must carry the tools, else the intersection narrows them away.
        result = _subagent_set(_config(("read_file", "run_command"), (spec,)))
        assert result is not None
        agent = result.get("runner")
        assert agent is not None
        # "run_command" maps to "bash" in dream
        assert "bash" in agent.tools
        assert "read_file" in agent.tools

    def test_projection_intersects_with_parent_tools(self) -> None:
        # A subagent tool the parent lacks is dropped — a subagent can only narrow, never widen.
        spec = SubagentSpec(
            name="narrower",
            description="Wants to write but parent can only read",
            tools=("read_file", "write_file"),
        )
        result = _subagent_set(_config(("read_file",), (spec,)))
        assert result is not None
        agent = result.get("narrower")
        assert agent is not None
        assert "read_file" in agent.tools
        assert "write_file" not in agent.tools

    def test_marketer_brand_critic_projects_correctly(self) -> None:
        config = role_beat_config(marketer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        assert "brand_critic" in result
        agent = result.get("brand_critic")
        assert agent is not None
        assert agent.max_turns == 4
        assert "read_file" in agent.tools
