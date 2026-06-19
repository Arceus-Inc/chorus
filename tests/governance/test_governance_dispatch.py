"""The governed-action dispatch seam — registry + 3-way resolution (§5 governance, Approach A).

The resolver is a thin dispatcher: it routes a decision to the handler registered for the approval's
action. An unregistered action fails closed; the third decision (request_revision) sends a task gate
back to ``todo`` and re-wakes the assignee.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.governance import (
    ApprovalDecision,
    GovernanceError,
    GovernanceRegistry,
    GovernanceResolver,
    UnregisteredAction,
)
from chorus.governance._actions import TaskGateAction
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
_USER = "operator"


def test_registry_is_fail_closed_on_an_unregistered_action(ledger: SqliteLedger) -> None:
    # only the task gate is registered; a budget_override approval has no handler → raises.
    resolver = GovernanceResolver(ledger, GovernanceRegistry.from_actions([TaskGateAction(ledger)]))
    ledger.approvals.request(
        Approval(
            id="a1",
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id="bi1",
            reason="override",
            action=ApprovalAction.BUDGET_OVERRIDE,
        )
    )
    with pytest.raises(UnregisteredAction):
        resolver.resolve("a1", decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW)


def test_registry_rejects_a_duplicate_handler(ledger: SqliteLedger) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        GovernanceRegistry.from_actions([TaskGateAction(ledger), TaskGateAction(ledger)])


def test_unregistered_action_is_a_governance_error(ledger: SqliteLedger) -> None:
    # UnregisteredAction subclasses GovernanceError so callers catch one type.
    assert issubclass(UnregisteredAction, GovernanceError)


def test_request_revision_sends_a_task_gate_back_to_todo_and_wakes_assignee(
    ledger: SqliteLedger,
) -> None:
    ledger.employees.create(Employee(id="alice", name="alice", role="engineer"))
    ledger.tasks.submit(
        Task(id="t1", intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="alice")
    )
    res = GovernanceResolver(ledger)
    approval = res.open_task_gate("t1", gate_kind=ApprovalGate.ACCEPTANCE, reason="needs work")

    outcome = res.resolve(
        approval.id,
        decision=ApprovalDecision.REQUEST_REVISION,
        decided_by_user_id=_USER,
        now=_NOW,
    )

    assert outcome.decision is ApprovalStatus.REVISION_REQUESTED
    assert outcome.subject_status == TaskStatus.TODO.value
    assert ledger.tasks.get("t1").status is TaskStatus.TODO  # type: ignore[union-attr]
    assert outcome.wakes_fired == 1
    assert any(w.employee_id == "alice" for w in ledger.wakes.queued())
    # the gate is resolved (no longer pending) → the subject's exact-once slot is freed.
    assert ledger.approvals.pending() == []
