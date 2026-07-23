"""The PM Critic subagent — typed DecisionCritique contract + capability-minimised manifest (§06).

The Critic is the PM's adversarial reviewer: it red-teams the drafted decision BEFORE `record_decision`
lands it — is the evidence sufficient, are the options real, does the confidence match the coverage? It
judges; it never records or edits. Its return is a typed :class:`DecisionCritique` (a decisive verdict
plus specific findings + the §06 new-angle/learnings contract).
"""

from __future__ import annotations

import pytest

from chorus_employee.pm._subagents import (
    CRITIC_SUBAGENT,
    DecisionCritique,
    Finding,
    decision_critique_output_schema,
)

pytestmark = pytest.mark.unit


def test_output_schema_is_derived_from_the_model() -> None:
    # single source of truth: the schema handed to dream is the model's own json schema
    assert decision_critique_output_schema() == DecisionCritique.model_json_schema()


def test_a_revise_critique_round_trips() -> None:
    critique = DecisionCritique.model_validate(
        {
            "verdict": "REVISE",
            "findings": [
                {
                    "dimension": "confidence_calibration",
                    "issue": "0.9 confidence rests on a single blog post",
                    "fix": "lower confidence to ~0.6 or add an independent source",
                }
            ],
            "new_angle": "the enterprise segment may have the opposite need — validate separately",
            "learnings": "a single-source claim should cap confidence near 0.6",
        }
    )
    assert critique.verdict == "REVISE"
    assert critique.findings[0].dimension == "confidence_calibration"
    assert isinstance(critique.findings[0], Finding)
    assert critique.notes == ""  # optional, defaults empty


def test_a_pass_critique_has_no_findings() -> None:
    critique = DecisionCritique.model_validate(
        {
            "verdict": "PASS",
            "findings": [],
            "new_angle": "none material",
            "learnings": "options were genuinely distinct and evidence covered the claim",
        }
    )
    assert critique.verdict == "PASS"
    assert critique.findings == []


def test_verdict_is_constrained_to_pass_or_revise() -> None:
    with pytest.raises(ValueError):
        DecisionCritique.model_validate(
            {"verdict": "MAYBE", "findings": [], "new_angle": "x", "learnings": "y"}
        )


def test_finding_dimension_is_constrained() -> None:
    with pytest.raises(ValueError):
        Finding.model_validate({"dimension": "vibes", "issue": "feels off", "fix": "think harder"})


def test_manifest_is_read_only_and_minimal() -> None:
    assert CRITIC_SUBAGENT.name == "critic"
    assert "read_file" in CRITIC_SUBAGENT.tools
    # read-only + never records: the Critic judges the decision, it does not make or write it
    assert "write_file" not in CRITIC_SUBAGENT.tools
    assert "run_command" not in CRITIC_SUBAGENT.tools
    assert "record_decision" not in CRITIC_SUBAGENT.tools
    assert (
        "spawn_subagent" not in CRITIC_SUBAGENT.tools
    )  # no depth-2; it judges what's in the worktree
    assert CRITIC_SUBAGENT.max_turns <= 6
    assert CRITIC_SUBAGENT.output_schema == decision_critique_output_schema()
