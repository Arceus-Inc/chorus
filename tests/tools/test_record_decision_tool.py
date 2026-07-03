"""RecordDecisionTool — the PM records a cited decision as a ledger object (§10, slice 3).

The tool is the boundary: it validates the model's input (pydantic), enforces the confidence floor
(refusing a floor-failing decision with a recovery hint rather than writing it), delegates the atomic
write to CapabilityService, and mirrors ``decision.json`` into the worktree (the DoD's check surface).
These tests drive ``execute`` directly with a written beat-context file standing in for the kernel.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import SqliteLedger
from chorus_tools import RecordDecisionTool

pytestmark = pytest.mark.integration

REV = "run_pm_1"


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _grounded_input() -> dict[str, object]:
    return {
        "option": "build live presence indicators",
        "rationale": "run opacity is the top support complaint",
        "confidence": 0.82,
        "outcome_metric": "'stuck' tickets drop 30% in 4 weeks",
        "revisit_trigger": "if flat in 4 weeks, reopen",
        "rejected_alternatives": [{"option": "second provider", "reason": "outages are rare"}],
        "claims": [
            {
                "text": "temporal surfaces execution state",
                "source_url": "https://a",
                "confidence": 0.9,
            }
        ],
    }


def _seed_beat(working_dir: Path) -> None:
    BeatContext(task_id="pm-task", run_id=REV, employee_id="piper").write(working_dir)


def test_records_a_grounded_decision_and_mirrors_the_json(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    _seed_beat(tmp_path)
    result = asyncio.run(RecordDecisionTool(ledger).execute(_grounded_input(), _ctx(tmp_path)))

    assert result.is_error is False
    assert result.structured["status"] == "success"
    decision_id = result.structured["decision_id"]
    assert any("plan.md" in action for action in result.structured["next_actions"])

    decisions = ledger.decisions.for_task("pm-task")
    assert len(decisions) == 1 and decisions[0].id == decision_id
    assert {c.source_url for c in ledger.claims.for_decisions([decision_id])} == {"https://a"}

    mirrored = json.loads((tmp_path / "decision.json").read_text(encoding="utf-8"))
    assert mirrored["decision_id"] == decision_id
    assert mirrored["claims"][0]["source_url"] == "https://a"


def test_refuses_a_decision_below_the_floor_with_a_recovery_hint(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    _seed_beat(tmp_path)
    weak = _grounded_input() | {"confidence": 0.4, "claims": []}
    result = asyncio.run(RecordDecisionTool(ledger).execute(weak, _ctx(tmp_path)))

    assert result.is_error is True
    assert result.structured["status"] == "blocked"
    assert any("researcher" in action for action in result.structured["next_actions"])
    assert result.metadata["root_cause"] == "confidence-below-floor"
    assert ledger.decisions.for_task("pm-task") == []  # nothing written
    assert not (tmp_path / "decision.json").exists()  # no mirror on refusal


def test_malformed_input_is_recovery_not_crash(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed_beat(tmp_path)
    bad = _grounded_input() | {"confidence": 1.5}  # out of range
    result = asyncio.run(RecordDecisionTool(ledger).execute(bad, _ctx(tmp_path)))
    assert result.is_error is True
    assert ledger.decisions.for_task("pm-task") == []


def test_is_idempotent_on_refire(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed_beat(tmp_path)
    tool = RecordDecisionTool(ledger)
    first = asyncio.run(tool.execute(_grounded_input(), _ctx(tmp_path)))
    second = asyncio.run(tool.execute(_grounded_input(), _ctx(tmp_path)))
    assert first.structured["decision_id"] == second.structured["decision_id"]
    assert len(ledger.decisions.for_task("pm-task")) == 1  # no duplicate


def test_declares_a_repo_write_trust_tier(ledger: SqliteLedger) -> None:
    assert RecordDecisionTool(ledger).declaration.tier_required == 1
