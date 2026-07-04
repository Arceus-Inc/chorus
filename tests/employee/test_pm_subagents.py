"""PM Researcher subagent — declaration, typed return contract, and manifest wiring (pm doc §06/§10).

The Researcher is the PM's Tier-1 evidence specialist: Piper spawns it mid-beat to answer one
evidence question and hand back a **typed, cited** :class:`ResearchBrief`. It is depth-2 — it itself
dispatches the shared Web-Research Orchestrator so no claim is written from memory — the exact shape
the Marketer's Strategist has. These tests pin the spec, the pydantic contract, and the capability
minimisation that keeps the child a subset of the parent.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus.roles import role_beat_config
from chorus_employee.pm import (
    RESEARCHER_SUBAGENT,
    EvidenceItem,
    ResearchBrief,
    pm_plugin,
    research_output_schema,
)

pytestmark = pytest.mark.unit


# --- Researcher declaration (§06) ---


class TestResearcherDeclaration:
    def test_subagent_name(self) -> None:
        assert RESEARCHER_SUBAGENT.name == "researcher"

    def test_max_turns_bounded(self) -> None:
        assert 0 < RESEARCHER_SUBAGENT.max_turns <= 12

    def test_carries_the_research_output_schema(self) -> None:
        schema = RESEARCHER_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert "evidence" in schema.get("properties", {})

    def test_is_depth_2_over_web_research(self) -> None:
        # It reuses the shared Web-Research Orchestrator (as the Strategist does) — cited facts, not
        # memory. Depth-2 requires spawn_subagent in its own tools (SubagentSpec enforces this).
        spawnable_names = {child.name for child in RESEARCHER_SUBAGENT.spawnable}
        assert "web_research" in spawnable_names
        assert "spawn_subagent" in RESEARCHER_SUBAGENT.tools

    def test_description_instructs_grounding_via_web_research(self) -> None:
        desc = RESEARCHER_SUBAGENT.description.lower()
        assert "web_research" in desc
        assert "source" in desc  # every claim carries a citation

    def test_description_keeps_the_researcher_off_the_decision(self) -> None:
        # It gathers evidence; the PM decides. It must not write the plan or make the call.
        desc = RESEARCHER_SUBAGENT.description.lower()
        assert "plan.md" in desc  # named explicitly as out of bounds
        assert "do not" in desc or "does not" in desc


# --- The typed return contract (pydantic is the single source of truth) ---


class TestResearchBriefSchema:
    def _valid_payload(self) -> dict[str, object]:
        return {
            "brief_file": "research_brief.md",
            "question": "how do agent products surface run progress and build user trust?",
            "evidence": [
                {
                    "claim": "workflow UIs expose execution state + pending work for debugging",
                    "source_url": "https://docs.temporal.io/web-ui",
                    "confidence": 0.8,
                }
            ],
            "new_angle": "trust may hinge on 'freshness' signals, not just an activity list",
            "gaps": "no quantified retention lift from presence indicators found yet",
            "learnings": "observability framing beats a raw event log when pitching the bet",
        }

    def test_valid_brief_parses(self) -> None:
        brief = ResearchBrief.model_validate(self._valid_payload())
        assert brief.brief_file == "research_brief.md"
        assert brief.evidence[0].source_url.startswith("https://")
        assert 0.0 <= brief.evidence[0].confidence <= 1.0

    def test_confidence_is_bounded_0_to_1(self) -> None:
        payload = self._valid_payload()
        payload["evidence"] = [
            {"claim": "x", "source_url": "https://x", "confidence": 1.4}  # out of range
        ]
        with pytest.raises(ValidationError):
            ResearchBrief.model_validate(payload)

    def test_evidence_item_requires_a_source(self) -> None:
        with pytest.raises(ValidationError):
            EvidenceItem.model_validate({"claim": "x", "source_url": "", "confidence": 0.5})

    def test_evidence_may_be_empty_when_nothing_verified(self) -> None:
        # Honest failure: the Researcher returns empty evidence + names the gap, never a fabricated cite.
        payload = self._valid_payload()
        payload["evidence"] = []
        brief = ResearchBrief.model_validate(payload)
        assert brief.evidence == []

    def test_output_schema_is_derived_from_the_model(self) -> None:
        # No hand-written schema to drift — it IS ResearchBrief.model_json_schema().
        assert research_output_schema() == ResearchBrief.model_json_schema()


# --- Manifest wiring + capability minimisation (§06) ---


class TestPmManifestWiresResearcher:
    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        assert "spawn_subagent" in pm_plugin().manifest.tools

    def test_manifest_declares_the_researcher(self) -> None:
        names = {sa.name for sa in pm_plugin().manifest.subagents}
        assert "researcher" in names

    def test_manifest_declares_the_critic(self) -> None:
        names = {sa.name for sa in pm_plugin().manifest.subagents}
        assert "critic" in names

    def test_subagent_tools_are_a_subset_of_parent_tools(self) -> None:
        parent_tools = set(pm_plugin().manifest.tools)
        for subagent in pm_plugin().manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in the PM's tools — narrower-wins violation"
                )

    def test_beat_config_flattens_the_depth_2_set(self) -> None:
        # role_beat_config surfaces both the declared Researcher and its depth-2 web_research child.
        config = role_beat_config(pm_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {"researcher", "web_research", "critic"}

    def test_brief_points_the_pm_at_the_researcher(self) -> None:
        from chorus_employee.pm import PM_BRIEF

        assert "researcher" in PM_BRIEF.lower()
