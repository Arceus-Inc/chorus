"""Marketer — Slice 1: Brand-Critic subagent declaration and factory wiring (design doc §06, §10)."""

from __future__ import annotations

import pytest

from chorus.roles import RoleBeatConfig, role_beat_config
from chorus.roles._subagent import SubagentSpec
from chorus.testing import open_test_ledger
from chorus_employee.marketer import (
    BRAND_CRITIC_SUBAGENT,
    CREATIVE_SUBAGENT,
    STRATEGIST_SUBAGENT,
    marketer_plugin,
)
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

    def test_brand_critic_carries_the_verdict_output_schema(self) -> None:
        # The verdict is a typed BrandVerdict: PASS/FAIL enum + violations, enforced at runtime.
        schema = BRAND_CRITIC_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"verdict", "violations"} <= set(schema["required"])
        assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]


# --- Strategist declaration (§06, §10) ---


class TestStrategistDeclaration:
    def test_subagent_name(self) -> None:
        assert STRATEGIST_SUBAGENT.name == "strategist"

    def test_strategist_carries_the_brief_output_schema(self) -> None:
        # The bet is a typed StrategyBrief: artifact path + structured bet + cited evidence.
        schema = STRATEGIST_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"brief_file", "hypothesis", "evidence"} <= set(schema["required"])


# --- Manifest integration ---


class TestMarketerManifestSubagents:
    def test_manifest_declares_brand_critic(self) -> None:
        plugin = marketer_plugin()
        assert any(sa.name == "brand_critic" for sa in plugin.manifest.subagents)

    def test_manifest_declares_web_research(self) -> None:
        # The shared Web-Research Orchestrator, passed DIRECTLY into the manifest (no with_web_research).
        plugin = marketer_plugin()
        assert any(sa.name == "web_research" for sa in plugin.manifest.subagents)

    def test_manifest_grants_web_extract_for_the_researcher(self) -> None:
        # web_research needs web_search + web_extract; the parent must hold both or narrower-wins strips
        # them from the child at materialize.
        plugin = marketer_plugin()
        assert "web_search" in plugin.manifest.tools
        assert "web_extract" in plugin.manifest.tools

    def test_web_research_carries_a_runtime_output_schema(self) -> None:
        plugin = marketer_plugin()
        wr = next(sa for sa in plugin.manifest.subagents if sa.name == "web_research")
        assert wr.output_schema is not None
        assert wr.output_schema.get("type") == "object"  # a JSON-schema object

    def test_brand_critic_gets_brand_lint_as_a_subagent_primitive(self) -> None:
        # §08: brand_lint is the Brand-Critic's deterministic primitive. It's a chorus capability tool,
        # identity-mapped in _CHORUS_TO_DREAM_TOOL so the projection keeps it; the parent holds it too
        # (narrower-wins). The projected child must carry it (the generator overlay is tools-unrestricted,
        # so the runtime parent-tool ceiling includes it as well).
        plugin = marketer_plugin()
        assert "brand_lint" in plugin.manifest.tools  # parent superset (needed by the projection)
        critic = next(sa for sa in plugin.manifest.subagents if sa.name == "brand_critic")
        assert "brand_lint" in critic.tools
        config = role_beat_config(plugin.manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("brand_critic")
        assert child is not None
        assert "brand_lint" in child.tools

    def test_brand_lint_is_actually_offered_to_the_critic_at_runtime(self) -> None:
        # Projection alone isn't enough — prove dream would OFFER brand_lint to the spawned critic via
        # its own tool-minimisation path. The generator manifest is tools=None (unrestricted), so the
        # subagent's parent ceiling = all registered tools; compute_minimum_toolset must keep brand_lint.
        from dream.permissions._types import SandboxTier
        from dream.roles._toolset import compute_minimum_toolset
        from dream.subagents._inline_executor import _build_subagent_manifest
        from dream.tools._registry import ToolSource

        import chorus_harness._factory as factory
        from chorus.roles import RoleRegistry

        config = role_beat_config(marketer_plugin().manifest)
        ledger = open_test_ledger()
        try:
            registry = factory._role_registry(factory.dream_tool_names(config.tools))
            for name in config.tools:
                cap = factory._capability_tool(name, ledger, RoleRegistry())
                if cap is not None:
                    registry.register(cap, source=ToolSource.DEFAULT)
            declarations = {t.name: t.declaration for t in registry.list_tools()}
            assert "brand_lint" in declarations  # registered as a real tool

            critic = _subagent_set(config).get("brand_critic")  # type: ignore[union-attr]
            assert critic is not None
            parent_ceiling = frozenset(declarations)  # generator role_allowed (tools=None → all)
            manifest = _build_subagent_manifest(critic, parent_tools=parent_ceiling)
            offered = compute_minimum_toolset(
                manifest, sandbox_tier=SandboxTier.REPO_WRITE_NET, declarations=declarations
            )
            assert "brand_lint" in offered  # dream offers it to the critic — not just projected
        finally:
            ledger.close()

    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        plugin = marketer_plugin()
        assert "spawn_subagent" in plugin.manifest.tools

    def test_subagent_tools_are_subset_of_parent_tools(self) -> None:
        plugin = marketer_plugin()
        parent_tools = set(plugin.manifest.tools)
        for subagent in plugin.manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in parent's tools — narrower-wins violation"
                )

    def test_beat_config_carries_the_subagents(self) -> None:
        config = role_beat_config(marketer_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {
            "brand_critic",
            "creative",
            "strategist",
            "web_research",
        }


# --- Creative / Copywriter declaration (§06, §10) ---


class TestCreativeDeclaration:
    def test_subagent_name(self) -> None:
        assert CREATIVE_SUBAGENT.name == "creative"

    def test_creative_is_a_write_agent(self) -> None:
        # §06: Creative drafts variants to the worktree — unlike the read-only Brand-Critic.
        assert "write_file" in CREATIVE_SUBAGENT.tools
        assert "read_file" in CREATIVE_SUBAGENT.tools

    def test_creative_self_lints(self) -> None:
        # It runs brand_lint on each variant so the set arrives pre-checked.
        assert "brand_lint" in CREATIVE_SUBAGENT.tools

    def test_creative_loads_the_brand_voice_skill(self) -> None:
        assert "skill" in CREATIVE_SUBAGENT.tools

    def test_creative_never_publishes(self) -> None:
        # No live surface, no command execution — it only drafts.
        assert "stage_go_live" not in CREATIVE_SUBAGENT.tools
        assert "run_command" not in CREATIVE_SUBAGENT.tools

    def test_creative_carries_the_output_schema(self) -> None:
        schema = CREATIVE_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert set(schema["required"]) == {"seed", "variants"}

    def test_description_names_the_seed_and_variants_contract(self) -> None:
        desc = CREATIVE_SUBAGENT.description
        assert "content_seed.md" in desc
        assert "candidates/" in desc

    def test_description_forbids_inventing_claims(self) -> None:
        # The hard rule: vary expression, preserve the seed's evidence (§10 claim discipline).
        desc = CREATIVE_SUBAGENT.description.lower()
        assert "claim" in desc

    def test_max_turns_bounded(self) -> None:
        assert 6 <= CREATIVE_SUBAGENT.max_turns <= 12


class TestCreativeManifestIntegration:
    def test_manifest_declares_creative(self) -> None:
        plugin = marketer_plugin()
        assert any(sa.name == "creative" for sa in plugin.manifest.subagents)

    def test_creative_tools_are_subset_of_parent(self) -> None:
        plugin = marketer_plugin()
        parent = set(plugin.manifest.tools)
        for tool in CREATIVE_SUBAGENT.tools:
            assert tool in parent, f"Creative tool {tool!r} not in parent (narrower-wins violation)"

    def test_projection_keeps_write_and_lint_on_the_child(self) -> None:
        config = role_beat_config(marketer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("creative")
        assert child is not None
        assert "write_file" in child.tools
        assert "brand_lint" in child.tools
        assert child.output_schema is not None


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
        assert agent.output_schema is None  # unset by default → no runtime enforcement

    def test_projection_carries_the_output_schema(self) -> None:
        # A declared output_schema reaches dream's Subagent, where the guardrail enforces it at runtime.
        schema = {"type": "object", "required": ["answer"]}
        spec = SubagentSpec(
            name="researcher",
            description="answers with structured JSON",
            tools=("read_file",),
            output_schema=schema,
        )
        result = _subagent_set(_config(("read_file",), (spec,)))
        assert result is not None
        agent = result.get("researcher")
        assert agent is not None
        assert agent.output_schema == schema

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
        assert agent.max_turns == 6
        assert "read_file" in agent.tools
        assert "brand_lint" in agent.tools
