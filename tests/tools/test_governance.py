"""The CEO's governance tools — the reverse edge of the strategy seam, exposed as dream tools.

These tests bind the tools to a fake :class:`dream.contracts.GovernancePort` (an in-memory stand-in for
horizon) and prove each verb reaches the port with the beat's identity — exactly as the manager's
``submit_task`` reaches the ledger. The composition-root wiring (factory ⇒ port) is covered separately;
here we pin the tools' own behaviour.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from dream.contracts import (
    GovDecision,
    GovernanceView,
    GovGoal,
    GovProposal,
)
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus_tools import (
    GOVERNANCE_TOOL_NAMES,
    GoalArchiveTool,
    GoalSetPriorityTool,
    GovernanceReadTool,
    ProposalApproveTool,
    ProposalRejectTool,
    governance_tool,
)

pytestmark = pytest.mark.unit

REV = "run_ceo_beat_1"


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


class FakeGovernance:
    """An in-memory GovernancePort — records the CEO's calls the way horizon's adapter would apply them."""

    def __init__(self) -> None:
        self.approved: list[tuple[str, str]] = []
        self.rejected: list[tuple[str, str, str]] = []
        self.reprioritised: list[tuple[str, str]] = []
        self.archived: list[str] = []

    def read_direction(self) -> GovernanceView:
        goal = GovGoal(
            goal_id="g1",
            title="lift activation",
            score=0.62,
            priority="high",
            health="green",
            status="active",
            metric="activation_rate",
            target="40%",
        )
        return GovernanceView(
            decisions=(GovDecision(decision_id="d1", statement="grow the core", goals=(goal,)),),
            proposals=(
                GovProposal(
                    proposal_id="p1",
                    statement="open a second market",
                    confidence=0.7,
                    evidence=3,
                ),
            ),
            decided=(
                GovProposal(
                    proposal_id="p0",
                    statement="launch the loyalty program",
                    status="approved",
                ),
            ),
        )

    def approve_proposal(self, proposal_id: str, *, by: str) -> str:
        self.approved.append((proposal_id, by))
        return "d2"

    def reject_proposal(self, proposal_id: str, *, by: str, reason: str = "") -> None:
        self.rejected.append((proposal_id, by, reason))

    def set_priority(self, goal_id: str, priority: str) -> str:
        self.reprioritised.append((goal_id, priority))
        return priority

    def archive_goal(self, goal_id: str) -> None:
        self.archived.append(goal_id)


def _beat(tmp_path: Path) -> None:
    BeatContext(task_id="C", run_id=REV, employee_id="ceo").write(tmp_path)


def test_governance_read_renders_the_direction(tmp_path: Path) -> None:
    result = asyncio.run(GovernanceReadTool(FakeGovernance()).execute({}, _ctx(tmp_path)))
    assert result.is_error is False
    assert "grow the core" in result.content
    assert "lift activation" in result.content
    assert "open a second market" in result.content
    # the decided proposal is surfaced so the CEO can cite it and a reviewer can confirm the work
    assert "RECENTLY DECIDED" in result.content
    assert "launch the loyalty program" in result.content
    assert result.structured == {"decisions": 1, "proposals": 1, "decided": 1}


def test_proposal_approve_reaches_the_port_with_the_ceo_identity(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    result = asyncio.run(ProposalApproveTool(port).execute({"proposal_id": "p1"}, _ctx(tmp_path)))
    assert result.is_error is False
    assert port.approved == [("p1", "ceo")]
    assert result.structured == {"proposal_id": "p1", "decision_id": "d2"}
    # the action is recorded to the worktree audit ledger so a reviewer can verify it from artifacts
    ledger = (tmp_path / "governance-ledger.md").read_text(encoding="utf-8")
    assert "APPROVED proposal p1" in ledger and "decision d2" in ledger


def test_audit_lines_are_stamped_with_the_beat_run_id(tmp_path: Path) -> None:
    """A standing worktree accumulates ledger lines across beats — the run stamp is what
    lets an evaluator tell THIS beat's actions from prior beats' (dream's per-beat task id
    IS the chorus run_id, so the stamp is directly matchable from the evaluator's paths)."""
    _beat(tmp_path)
    port = FakeGovernance()
    asyncio.run(ProposalApproveTool(port).execute({"proposal_id": "p1"}, _ctx(tmp_path)))
    BeatContext(task_id="C", run_id="run-next-beat", employee_id="ceo").write(tmp_path)
    asyncio.run(ProposalRejectTool(port).execute({"proposal_id": "p2"}, _ctx(tmp_path)))

    lines = (tmp_path / "governance-ledger.md").read_text(encoding="utf-8").splitlines()
    approve = next(line for line in lines if "APPROVED proposal p1" in line)
    reject = next(line for line in lines if "REJECTED proposal p2" in line)
    assert f"[run {REV}]" in approve
    assert "[run run-next-beat]" in reject


def test_proposal_reject_carries_the_reason(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    result = asyncio.run(
        ProposalRejectTool(port).execute(
            {"proposal_id": "p1", "reason": "too thin"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False
    assert port.rejected == [("p1", "ceo", "too thin")]


def test_goal_set_priority_steers_the_goal(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute({"goal_id": "g1", "priority": "high"}, _ctx(tmp_path))
    )
    assert result.is_error is False
    assert port.reprioritised == [("g1", "high")]


def test_goal_set_priority_maps_a_synonym_to_a_band(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute({"goal_id": "g1", "priority": "CRITICAL"}, _ctx(tmp_path))
    )
    assert result.is_error is False
    assert port.reprioritised == [("g1", "high")]  # critical → high, not a raw error


def test_goal_set_priority_refuses_an_unknown_band(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute(
            {"goal_id": "g1", "priority": "yesterday"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is True
    assert port.reprioritised == []  # nothing applied
    assert "low, medium, high" in result.content


def test_proposal_approve_wraps_a_port_error_cleanly(tmp_path: Path) -> None:
    _beat(tmp_path)

    class Boom(FakeGovernance):
        def approve_proposal(self, proposal_id: str, *, by: str) -> str:
            raise ValueError("no such proposal")

    result = asyncio.run(
        ProposalApproveTool(Boom()).execute({"proposal_id": "gone"}, _ctx(tmp_path))
    )
    assert result.is_error is True
    assert "governance_read" in result.content  # guides the CEO to re-read, no raw traceback


def test_goal_archive_retires_the_goal(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(GoalArchiveTool(port).execute({"goal_id": "g1"}, _ctx(tmp_path)))
    assert result.is_error is False
    assert port.archived == ["g1"]


def test_governance_tool_maps_every_declared_name() -> None:
    port = FakeGovernance()
    for name in GOVERNANCE_TOOL_NAMES:
        tool = governance_tool(name, port)
        assert tool is not None and tool.name == name
    assert governance_tool("not_a_governance_tool", port) is None
