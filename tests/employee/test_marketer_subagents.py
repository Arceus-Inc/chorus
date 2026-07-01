"""Marketer — Slice 1: Brand-Critic subagent declaration and factory wiring (design doc §06, §10)."""

from __future__ import annotations

import pytest

from chorus.roles._manifest import SubagentDecl
from chorus_employee.marketer import BRAND_CRITIC_SUBAGENT, marketer_plugin
from chorus_harness._factory import _project_subagents

pytestmark = pytest.mark.integration


# --- Brand-Critic declaration ---


class TestBrandCriticDeclaration:
    def test_subagent_name(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.name == "brand_critic"

    def test_subagent_is_read_only(self) -> None:
        assert "write_file" not in BRAND_CRITIC_SUBAGENT.tools
        assert "run_command" not in BRAND_CRITIC_SUBAGENT.tools
        assert "read_file" in BRAND_CRITIC_SUBAGENT.tools

    def test_subagent_has_system_prompt(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.system_prompt is not None
        assert "Brand-Critic" in BRAND_CRITIC_SUBAGENT.system_prompt

    def test_subagent_max_turns_bounded(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.max_turns <= 6

    def test_subagent_depth_is_1(self) -> None:
        assert BRAND_CRITIC_SUBAGENT.depth == 1

    def test_subagent_description_mentions_brand_voice(self) -> None:
        assert "brand" in BRAND_CRITIC_SUBAGENT.description.lower()
        assert "voice" in BRAND_CRITIC_SUBAGENT.description.lower()

    def test_system_prompt_instructs_pass_fail_verdict(self) -> None:
        prompt = BRAND_CRITIC_SUBAGENT.system_prompt
        assert "PASS" in prompt
        assert "FAIL" in prompt

    def test_system_prompt_instructs_read_only(self) -> None:
        prompt = BRAND_CRITIC_SUBAGENT.system_prompt
        assert "read-only" in prompt.lower() or "read only" in prompt.lower()


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


# --- Factory projection ---


class TestProjectSubagents:
    def test_empty_decls_returns_none(self) -> None:
        assert _project_subagents(()) is None

    def test_single_subagent_projects_to_subagent_set(self) -> None:
        decl = SubagentDecl(
            name="test_agent",
            description="A test subagent",
            tools=("read_file",),
            system_prompt="You are a test agent.",
            max_turns=3,
            depth=1,
        )
        result = _project_subagents((decl,))
        assert result is not None
        assert "test_agent" in result
        assert len(result) == 1

    def test_projected_subagent_preserves_fields(self) -> None:
        decl = SubagentDecl(
            name="critic",
            description="Reviews things",
            tools=("read_file",),
            system_prompt="Be critical.",
            max_turns=4,
            depth=1,
        )
        result = _project_subagents((decl,))
        agent = result.get("critic")
        assert agent is not None
        assert agent.name == "critic"
        assert agent.description == "Reviews things"
        assert agent.system_prompt == "Be critical."
        assert agent.max_turns == 4
        assert agent.depth == 1

    def test_projected_tools_are_dream_names(self) -> None:
        decl = SubagentDecl(
            name="runner",
            description="Runs commands",
            tools=("read_file", "run_command"),
            max_turns=2,
        )
        result = _project_subagents((decl,))
        agent = result.get("runner")
        # "run_command" maps to "bash" in dream
        assert "bash" in agent.tools
        assert "read_file" in agent.tools

    def test_marketer_brand_critic_projects_correctly(self) -> None:
        plugin = marketer_plugin()
        result = _project_subagents(plugin.manifest.subagents)
        assert result is not None
        assert "brand_critic" in result
        agent = result.get("brand_critic")
        assert agent.max_turns == 4
        assert "read_file" in agent.tools
