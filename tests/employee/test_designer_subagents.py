"""Designer — subagents slice: Design-Critic, Explorer, and UX-Researcher declarations + wiring.

Structural twin of ``test_marketer_subagents.py`` (design doc §06, §10). The *declaration*-level
tests run everywhere; the *projection*-level tests (``_subagent_set`` / runtime-offer) exercise
dream's ``Subagent`` projection, which on this branch requires a ``spawnable``-aware dream. They are
guarded by :data:`_DREAM_HAS_SPAWNABLE` so the suite stays green against an older dream and light up
automatically once dream is updated (see session note: dream/chorus ``spawnable`` version mismatch).
"""

from __future__ import annotations

import pytest

from chorus.roles import role_beat_config
from chorus.testing import open_test_ledger
from chorus_employee.designer import (
    DESIGN_CRITIC_SUBAGENT,
    designer_plugin,
)
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration

# dream's Subagent must accept `spawnable=` before the factory can project depth-2 specs. When the
# installed dream predates that field, chorus's `_project_spec` raises TypeError — skip projection
# tests (not designer bugs) rather than fail them. Declaration-level coverage is unaffected.
try:  # pragma: no cover - trivial capability probe
    from dream.subagents._declaration import Subagent as _DreamSubagent

    _DREAM_HAS_SPAWNABLE = "spawnable" in getattr(_DreamSubagent, "__dataclass_fields__", {})
except Exception:  # pragma: no cover - dream import shape changed
    _DREAM_HAS_SPAWNABLE = False

_needs_spawnable = pytest.mark.skipif(
    not _DREAM_HAS_SPAWNABLE,
    reason="installed dream.Subagent lacks `spawnable`; factory projection blocked (pre-existing env mismatch)",
)


# --- Design-Critic declaration (Brand-Critic twin) ---


class TestDesignCriticDeclaration:
    def test_subagent_name(self) -> None:
        assert DESIGN_CRITIC_SUBAGENT.name == "design_critic"

    def test_subagent_is_read_only(self) -> None:
        assert "write_file" not in DESIGN_CRITIC_SUBAGENT.tools
        assert "run_command" not in DESIGN_CRITIC_SUBAGENT.tools
        assert "read_file" in DESIGN_CRITIC_SUBAGENT.tools

    def test_subagent_max_turns_bounded(self) -> None:
        assert DESIGN_CRITIC_SUBAGENT.max_turns <= 6

    def test_subagent_description_mentions_design_and_accessibility(self) -> None:
        # The child's system prompt is generated from the description, so the full brief lives there.
        desc = DESIGN_CRITIC_SUBAGENT.description.lower()
        assert "design" in desc
        assert "accessib" in desc or "a11y" in desc

    def test_description_instructs_pass_fail_verdict(self) -> None:
        desc = DESIGN_CRITIC_SUBAGENT.description
        assert "PASS" in desc
        assert "FAIL" in desc

    def test_description_instructs_read_only(self) -> None:
        desc = DESIGN_CRITIC_SUBAGENT.description.lower()
        assert "read-only" in desc or "read only" in desc

    def test_design_critic_grounds_verdict_on_design_lint(self) -> None:
        # §08: design_lint is the Critic's deterministic primitive — it runs it first, then reasons.
        assert "design_lint" in DESIGN_CRITIC_SUBAGENT.tools
        assert "design_lint" in DESIGN_CRITIC_SUBAGENT.description

    def test_design_critic_carries_the_verdict_output_schema(self) -> None:
        schema = DESIGN_CRITIC_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"verdict", "violations"} <= set(schema["required"])
        assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]


# --- Manifest integration ---


class TestDesignerManifestSubagents:
    def test_manifest_declares_design_critic(self) -> None:
        plugin = designer_plugin()
        assert any(sa.name == "design_critic" for sa in plugin.manifest.subagents)

    def test_manifest_omits_craft_personas(self) -> None:
        plugin = designer_plugin()
        names = {sa.name for sa in plugin.manifest.subagents}
        assert "explorer" not in names
        assert "ux_researcher" not in names

    def test_manifest_declares_web_research(self) -> None:
        # The shared Web-Research Orchestrator, passed DIRECTLY into the manifest so the UX-Researcher
        # can dispatch it (and narrower-wins keeps its web tools).
        plugin = designer_plugin()
        assert any(sa.name == "web_research" for sa in plugin.manifest.subagents)

    def test_manifest_grants_web_tools_for_the_researcher(self) -> None:
        plugin = designer_plugin()
        assert "browser_run" in plugin.manifest.tools
        assert "browser_run" in plugin.manifest.tools

    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        plugin = designer_plugin()
        assert "spawn_subagent" in plugin.manifest.tools

    def test_design_critic_gets_design_lint_as_a_subagent_primitive(self) -> None:
        plugin = designer_plugin()
        assert "design_lint" in plugin.manifest.tools  # parent superset (needed by the projection)
        critic = next(sa for sa in plugin.manifest.subagents if sa.name == "design_critic")
        assert "design_lint" in critic.tools

    def test_subagent_tools_are_subset_of_parent_tools(self) -> None:
        plugin = designer_plugin()
        parent_tools = set(plugin.manifest.tools)
        for subagent in plugin.manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in parent's tools — narrower-wins violation"
                )

    def test_beat_config_carries_the_subagents(self) -> None:
        config = role_beat_config(designer_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {
            "design_critic",
            "web_research",
        }

    def test_brief_does_not_instruct_removed_personas(self) -> None:
        from chorus_employee.designer import DESIGNER_BRIEF

        assert 'spawn_subagent(name="ux_researcher"' not in DESIGNER_BRIEF
        assert 'spawn_subagent(name="explorer"' not in DESIGNER_BRIEF
        assert 'spawn_subagent(name="design_critic"' in DESIGNER_BRIEF


# --- Factory projection (guarded on dream `spawnable` support) ---


@_needs_spawnable
class TestDesignerProjection:
    def test_design_critic_projects_with_design_lint(self) -> None:
        config = role_beat_config(designer_plugin().manifest)
        result = _subagent_set(config)
        assert result is not None
        child = result.get("design_critic")
        assert child is not None
        assert child.max_turns <= 6
        assert "read_file" in child.tools
        assert "design_lint" in child.tools
        assert "write_file" not in child.tools  # read-only survives projection

    def test_design_lint_is_actually_offered_to_the_critic_at_runtime(self) -> None:
        from dream.permissions._types import SandboxTier
        from dream.roles._toolset import compute_minimum_toolset
        from dream.subagents._inline_executor import _build_subagent_manifest
        from dream.tools._registry import ToolSource

        import chorus_harness._factory as factory
        from chorus.roles import RoleRegistry

        config = role_beat_config(designer_plugin().manifest)
        ledger = open_test_ledger()
        try:
            registry = factory._role_registry(factory.dream_tool_names(config.tools))
            for name in config.tools:
                cap = factory._capability_tool(name, ledger, RoleRegistry())
                if cap is not None:
                    registry.register(cap, source=ToolSource.DEFAULT)
            declarations = {t.name: t.declaration for t in registry.list_tools()}
            assert "design_lint" in declarations

            critic = _subagent_set(config).get("design_critic")  # type: ignore[union-attr]
            assert critic is not None
            parent_ceiling = frozenset(declarations)
            manifest = _build_subagent_manifest(critic, parent_tools=parent_ceiling)
            offered = compute_minimum_toolset(
                manifest, sandbox_tier=SandboxTier.REPO_WRITE_NET, declarations=declarations
            )
            assert "design_lint" in offered
        finally:
            ledger.close()
