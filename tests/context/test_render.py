"""Pure rendering checks for the typed task context plane."""

from __future__ import annotations

from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.context import (
    AncestryKind,
    AncestryLink,
    BudgetPosition,
    Citation,
    ContextAudience,
    DoDRequirement,
    InboxItem,
    PriorBeat,
    SiblingFailure,
    TaskContextPacket,
    TaskContract,
    Truncation,
    render_task_context,
)


def _packet() -> TaskContextPacket:
    return TaskContextPacket(
        task_id="task-1",
        contract=TaskContract("Implement the packet", (DoDRequirement("command", "pytest -q"),)),
        ancestry=(AncestryLink(AncestryKind.GOAL, "goal-1", "Ship reliability", "active"),),
        prior_beats=(
            PriorBeat(
                run_id="run-1",
                phase=LandedPhase.NEEDS_REWORK,
                recovery_hint=RecoveryHint.REWORK,
                evaluator_notes=("cover the retry branch",),
                files_touched=("src/retry.py",),
                todo_digest="re-run focused tests",
                citation=Citation("ledger.run_carryover:run-1", "landed beat carryover"),
            ),
        ),
        inbox=(InboxItem("message-1", "lead", "prioritize the regression", "task-1"),),
        sibling_failures=(
            SiblingFailure(
                "task-old",
                "rejected",
                ("do not weaken the assertion",),
                Citation("ledger.task:task-old", "same-assignee corrective sibling failure"),
            ),
        ),
        budget=BudgetPosition(25, 100, 1),
        citations=(
            Citation("ledger.task:task-1", "assigned task and contract"),
            Citation("ledger.run_carryover:run-1", "landed beat carryover"),
            Citation("ledger.task:task-old", "same-assignee corrective sibling failure"),
        ),
        truncation=(Truncation("prior_beats", 1, "bounded deterministic projection"),),
    )


def test_planner_and_generator_get_recovery_but_evaluator_does_not() -> None:
    packet = _packet()

    planner = render_task_context(packet, ContextAudience.PLANNER)
    generator = render_task_context(packet, ContextAudience.GENERATOR)
    evaluator = render_task_context(packet, ContextAudience.EVALUATOR)

    assert "cover the retry branch" in planner
    assert "cover the retry branch" in generator
    assert "prioritize the regression" not in planner
    assert "prioritize the regression" in generator
    assert "cover the retry branch" not in evaluator
    assert "do not weaken the assertion" not in evaluator
    assert "prioritize the regression" not in evaluator
    assert "pytest -q" in evaluator
    assert "run-1" not in evaluator
    assert "task-old" not in evaluator
    assert "ledger.run_carryover" not in evaluator
    assert "context truncated" not in evaluator
