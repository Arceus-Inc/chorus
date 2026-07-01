"""Web-Research Orchestrator — shared subagent declaration, opt-in wiring, and output contract."""

from __future__ import annotations

import pytest

from chorus.roles import role_beat_config
from chorus.roles._manifest import RoleManifest, SandboxTier
from chorus.roles._subagent import SubagentSpec
from chorus_harness._factory import _subagent_set, dream_tool_names
from swarm.web_research_orchestrator import (
    WEB_RESEARCH_ORCHESTRATOR,
    WebResearchOutput,
    web_research_output_schema,
    with_web_research,
)

pytestmark = pytest.mark.integration


def _base_manifest(**kw) -> RoleManifest:
    """A minimal role manifest to opt into web research (no web tools by default)."""
    return RoleManifest(system_prompt="test role", tools=("read_file",), **kw)


# --- declaration -----------------------------------------------------------


class TestDeclaration:
    def test_is_a_subagent_spec(self) -> None:
        assert isinstance(WEB_RESEARCH_ORCHESTRATOR, SubagentSpec)
        assert WEB_RESEARCH_ORCHESTRATOR.name == "web_research"

    def test_uses_only_the_two_web_tools(self) -> None:
        assert WEB_RESEARCH_ORCHESTRATOR.tools == ("web_search", "web_extract")

    def test_has_no_write_or_command_or_browser_tools(self) -> None:
        for forbidden in ("write_file", "run_command", "read_file", "open", "get_text", "eval"):
            assert forbidden not in WEB_RESEARCH_ORCHESTRATOR.tools

    def test_turn_budget_is_bounded(self) -> None:
        assert 0 < WEB_RESEARCH_ORCHESTRATOR.max_turns <= 16

    def test_brief_carries_policy_ladder_and_contract(self) -> None:
        desc = WEB_RESEARCH_ORCHESTRATOR.description
        assert "web_search" in desc and "web_extract" in desc
        assert "needs_render" in desc  # the escalation signal
        assert "citation_graph" in desc  # the output contract
        assert "confidence" in desc
        low = desc.lower()
        assert "independent" in low  # triangulation rule
        assert "saturat" in low or "consecutive" in low  # the ladder


# --- opt-in wiring ---------------------------------------------------------


class TestWithWebResearch:
    def test_appends_the_subagent(self) -> None:
        m = with_web_research(_base_manifest())
        names = [s.name for s in m.subagents]
        assert names.count("web_research") == 1

    def test_grants_the_required_tools(self) -> None:
        m = with_web_research(_base_manifest())
        for tool in ("spawn_subagent", "web_search", "web_extract"):
            assert tool in m.tools
        assert "read_file" in m.tools  # original tools preserved

    def test_raises_sandbox_to_net(self) -> None:
        m = with_web_research(_base_manifest(sandbox=SandboxTier.REPO_WRITE))
        assert m.sandbox == SandboxTier.REPO_WRITE_NET

    def test_does_not_downgrade_unrestricted(self) -> None:
        m = with_web_research(_base_manifest(sandbox=SandboxTier.UNRESTRICTED))
        assert m.sandbox == SandboxTier.UNRESTRICTED

    def test_is_idempotent(self) -> None:
        once = with_web_research(_base_manifest())
        twice = with_web_research(once)
        assert [s.name for s in twice.subagents].count("web_research") == 1
        assert twice.tools == once.tools

    def test_subagent_tools_are_subset_of_parent(self) -> None:
        m = with_web_research(_base_manifest())
        parent = set(m.tools)
        assert set(WEB_RESEARCH_ORCHESTRATOR.tools) <= parent


# --- factory projection (narrower-wins survives to the real SubagentSet) ----


class TestFactoryProjection:
    def test_projects_into_a_subagent_set_with_both_tools(self) -> None:
        config = role_beat_config(with_web_research(_base_manifest()))
        sset = _subagent_set(config)
        assert sset is not None
        agent = next(a for a in sset.agents.values() if a.name == "web_research")
        # the two web tools map to real dream builtins and survive the parent intersection
        assert set(agent.tools) == set(dream_tool_names(("web_search", "web_extract")))


# --- output contract -------------------------------------------------------


class TestOutputContract:
    def test_validates_a_well_formed_result(self) -> None:
        out = WebResearchOutput.model_validate(
            {
                "answer": "Spain won Euro 2024.",
                "findings": [{"claim": "Spain won", "sources": [1, 2]}],
                "citation_graph": {
                    "sources": [
                        {"id": 1, "url": "https://a.com", "title": "A"},
                        {"id": 2, "url": "https://b.com", "title": "B"},
                    ],
                    "edges": [{"claim_idx": 0, "source_id": 1}],
                },
                "assumptions": [],
                "confidence": 0.9,
                "trail": [{"query": "euro 2024 winner", "opened": ["https://a.com"]}],
            }
        )
        assert out.confidence == 0.9
        assert out.findings[0].sources == [1, 2]

    def test_confidence_is_bounded(self) -> None:
        with pytest.raises(ValueError):
            WebResearchOutput.model_validate({"answer": "x", "confidence": 1.5})

    def test_schema_export_has_required_keys(self) -> None:
        schema = web_research_output_schema()
        assert schema["type"] == "object"
        assert "answer" in schema["properties"]
        assert "citation_graph" in schema["properties"]
