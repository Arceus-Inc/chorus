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
    ProfessionCapacity,
)
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.testing import uid
from chorus_tools import (
    GOVERNANCE_TOOL_NAMES,
    GoalArchiveTool,
    GoalSetPriorityTool,
    GovernanceReadTool,
    ProposalApproveTool,
    ProposalRejectTool,
    RoadmapProposeTool,
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
        self.roadmaps: list[tuple[str, list, str | None]] = []

    def read_direction(self) -> GovernanceView:
        goal = GovGoal(
            goal_id=uid("g1"),
            title="lift activation",
            score=0.62,
            priority="high",
            health="green",
            status="active",
            metric="activation_rate",
            target="40%",
        )
        return GovernanceView(
            decisions=(
                GovDecision(decision_id=uid("d1"), statement="grow the core", goals=(goal,)),
            ),
            proposals=(
                GovProposal(
                    proposal_id=uid("p1"),
                    statement="open a second market",
                    confidence=0.7,
                    evidence=3,
                ),
            ),
            decided=(
                GovProposal(
                    proposal_id=uid("p0"),
                    statement="launch the loyalty program",
                    status="approved",
                ),
            ),
            capacity=(
                ProfessionCapacity(
                    profession="frontend_engineer",
                    eligible=3,
                    running=1,
                    assigned_nonterminal=2,
                    queued_wakes=0,
                    budget_blocked=0,
                    budget_headroom_cents=100_000,
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

    def propose_roadmap(self, statement: str, specs, *, by: str | None = None) -> str:
        self.roadmaps.append((statement, list(specs), by))
        return "d3"


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
    # the capacity snapshot is shown so the CEO can size the roadmap to it
    assert "CAPACITY" in result.content and "frontend_engineer" in result.content
    assert result.structured == {"decisions": 1, "proposals": 1, "decided": 1, "capacity": 1}


def test_proposal_approve_reaches_the_port_with_the_ceo_identity(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    result = asyncio.run(
        ProposalApproveTool(port).execute({"proposal_id": uid("p1")}, _ctx(tmp_path))
    )
    assert result.is_error is False
    assert port.approved == [(uid("p1"), "ceo")]
    assert result.structured == {"proposal_id": uid("p1"), "decision_id": "d2"}
    # the action is recorded to the worktree audit ledger so a reviewer can verify it from artifacts
    ledger = (tmp_path / "governance-ledger.md").read_text(encoding="utf-8")
    assert f"APPROVED proposal {uid('p1')}" in ledger and "decision d2" in ledger


def test_audit_lines_are_stamped_with_the_beat_run_id(tmp_path: Path) -> None:
    """A standing worktree accumulates ledger lines across beats — the run stamp is what
    lets an evaluator tell THIS beat's actions from prior beats' (dream's per-beat task id
    IS the chorus run_id, so the stamp is directly matchable from the evaluator's paths)."""
    _beat(tmp_path)
    port = FakeGovernance()
    asyncio.run(ProposalApproveTool(port).execute({"proposal_id": uid("p1")}, _ctx(tmp_path)))
    BeatContext(task_id="C", run_id="run-next-beat", employee_id="ceo").write(tmp_path)
    asyncio.run(ProposalRejectTool(port).execute({"proposal_id": "p2"}, _ctx(tmp_path)))

    lines = (tmp_path / "governance-ledger.md").read_text(encoding="utf-8").splitlines()
    approve = next(line for line in lines if f"APPROVED proposal {uid('p1')}" in line)
    reject = next(line for line in lines if "REJECTED proposal p2" in line)
    assert f"[run {REV}]" in approve
    assert "[run run-next-beat]" in reject


def test_proposal_reject_carries_the_reason(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    result = asyncio.run(
        ProposalRejectTool(port).execute(
            {"proposal_id": uid("p1"), "reason": "too thin"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False
    assert port.rejected == [(uid("p1"), "ceo", "too thin")]


def test_goal_set_priority_steers_the_goal(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute(
            {"goal_id": uid("g1"), "priority": "high"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False
    assert port.reprioritised == [(uid("g1"), "high")]


def test_goal_set_priority_maps_a_synonym_to_a_band(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute(
            {"goal_id": uid("g1"), "priority": "CRITICAL"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False
    assert port.reprioritised == [(uid("g1"), "high")]  # critical → high, not a raw error


def test_goal_set_priority_refuses_an_unknown_band(tmp_path: Path) -> None:
    port = FakeGovernance()
    result = asyncio.run(
        GoalSetPriorityTool(port).execute(
            {"goal_id": uid("g1"), "priority": "yesterday"}, _ctx(tmp_path)
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
    result = asyncio.run(GoalArchiveTool(port).execute({"goal_id": uid("g1")}, _ctx(tmp_path)))
    assert result.is_error is False
    assert port.archived == [uid("g1")]


def test_governance_tool_maps_every_declared_name() -> None:
    port = FakeGovernance()
    for name in GOVERNANCE_TOOL_NAMES:
        tool = governance_tool(name, port)
        assert tool is not None and tool.name == name
    assert governance_tool("not_a_governance_tool", port) is None


def test_roadmap_propose_reaches_the_port_with_the_ceo_identity(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    result = asyncio.run(
        RoadmapProposeTool(port).execute(
            {
                "statement": "Ship the calm suite",
                "goals": [
                    {"title": "Notes app", "metric": "shipped", "target": "v1", "score": 0.8},
                    {
                        "title": "Timer",
                        "metric": "shipped",
                        "target": "v1",
                        "score": 0.6,
                        "key": "t",
                        "rationale": "focus loop",
                    },
                ],
            },
            _ctx(tmp_path),
        )
    )
    assert result.is_error is False
    assert result.structured == {"decision_id": "d3", "goals": 2}
    statement, specs, by = port.roadmaps[0]
    assert (statement, by) == ("Ship the calm suite", "ceo")
    assert specs[0] == {"title": "Notes app", "metric": "shipped", "target": "v1", "score": 0.8}
    assert specs[1]["key"] == "t" and specs[1]["rationale"] == "focus loop"
    ledger = (tmp_path / "governance-ledger.md").read_text(encoding="utf-8")
    assert "PROPOSED roadmap → decision d3" in ledger


def test_roadmap_propose_omits_empty_optional_fields(tmp_path: Path) -> None:
    _beat(tmp_path)
    port = FakeGovernance()
    asyncio.run(
        RoadmapProposeTool(port).execute(
            {"statement": "M", "goals": [{"title": "A", "metric": "m", "target": "t", "score": 0.5}]},
            _ctx(tmp_path),
        )
    )
    _, specs, _ = port.roadmaps[0]
    # a flat goal with no key/deps/rationale carries only the four core fields (no empty keys leak through)
    assert specs == [{"title": "A", "metric": "m", "target": "t", "score": 0.5}]


def test_roadmap_propose_wraps_a_ledger_rejection_cleanly(tmp_path: Path) -> None:
    _beat(tmp_path)

    class Boom(FakeGovernance):
        def propose_roadmap(self, statement: str, specs, *, by: str | None = None) -> str:
            raise ValueError("goal 'A' needs a target")

    result = asyncio.run(
        RoadmapProposeTool(Boom()).execute(
            {"statement": "M", "goals": [{"title": "A", "metric": "m", "target": "t", "score": 0.5}]},
            _ctx(tmp_path),
        )
    )
    assert result.is_error is True
    assert "refused" in result.content and "needs a target" in result.content
