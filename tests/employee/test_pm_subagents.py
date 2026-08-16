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
    CRITIC_SUBAGENT,
    EvidenceItem,
    ResearchBrief,
    pm_plugin,
    research_output_schema,
)

pytestmark = pytest.mark.unit


# --- Critic declaration (retained isolation earner) ---


class TestCriticDeclaration:
    def test_subagent_name(self) -> None:
        assert CRITIC_SUBAGENT.name == "critic"

    def test_carries_the_critique_output_schema(self) -> None:
        schema = CRITIC_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"


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


class TestPmManifestWiresLeanRoster:
    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        assert "spawn_subagent" in pm_plugin().manifest.tools

    def test_manifest_declares_isolation_earners_only(self) -> None:
        names = {sa.name for sa in pm_plugin().manifest.subagents}
        assert names == {"web_research", "critic"}

    def test_subagent_tools_are_a_subset_of_parent_tools(self) -> None:
        parent_tools = set(pm_plugin().manifest.tools)
        for subagent in pm_plugin().manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in the PM's tools — narrower-wins violation"
                )

    def test_beat_config_carries_the_lean_set(self) -> None:
        config = role_beat_config(pm_plugin().manifest)
        assert {sa.name for sa in config.subagents} == {"web_research", "critic"}

    def test_brief_points_the_pm_at_web_research_and_critic(self) -> None:
        from chorus_employee.pm import PM_BRIEF

        assert 'spawn_subagent(name="web_research"' in PM_BRIEF
        assert 'spawn_subagent(name="critic"' in PM_BRIEF
        assert 'spawn_subagent(name="researcher"' not in PM_BRIEF
