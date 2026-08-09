"""The governance resolver — open a task gate, resolve it, the task moves (spec 04 §5).

Both gate kinds in both decisions, plus the error paths (unknown / already-decided / non-task /
missing gate). Every assertion checks the durable ledger effect, not just the returned outcome.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.governance import (
    ApprovalDecision,
    GovernanceError,
    GovernanceResolver,
    HumanAuthorization,
    ResolveOutcome,
)
from chorus.ledger import (
    Approval,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    AuthenticationMethod,
    DodStatus,
    Ledger,
    Task,
    TaskStatus,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
_USER = "operator"


def _resolver(ledger: Ledger) -> GovernanceResolver:
    return GovernanceResolver(ledger)


def _authorization() -> HumanAuthorization:
    return HumanAuthorization(
        decision_id=uid("decision"),
        user_id=_USER,
        method=AuthenticationMethod.SESSION,
        authenticated_at=_NOW,
        nonce=uid("nonce"),
        decided_at=_NOW,
        request_id="resolver-test",
        request_hash="sha256:resolver-test",
    )


def _task(ledger: Ledger, task_id: str = uid("t1"), *, assignee: str | None = "alice") -> None:
    if assignee is not None:
        ledger.employees.create(Employee(id=assignee, name=assignee, role="engineer"))
    ledger.tasks.submit(
        Task(
            id=task_id, intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id=assignee
        )
    )


# -- open_task_gate ---------------------------------------------------------------------------------


def test_open_parks_the_task_and_opens_a_pending_gate(ledger: Ledger) -> None:
    _task(ledger)
    approval = _resolver(ledger).open_task_gate(
        uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off the spec"
    )
    assert approval.status is ApprovalStatus.PENDING
    assert approval.gate_kind is ApprovalGate.ACCEPTANCE
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert [a.id for a in ledger.approvals.pending()] == [approval.id]


def test_open_unknown_task_errors(ledger: Ledger) -> None:
    with pytest.raises(GovernanceError):
        _resolver(ledger).open_task_gate(
            uid("ghost"), gate_kind=ApprovalGate.ACCEPTANCE, reason="x"
        )


def test_open_terminal_task_errors(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.DONE))
    with pytest.raises(GovernanceError):
        _resolver(ledger).open_task_gate(
            uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="x"
        )


def test_open_second_gate_on_a_gated_task_errors_as_governance(ledger: Ledger) -> None:
    # A duplicate pending gate is a domain condition (GovernanceError), not a leaked low-level
    # sqlite3.IntegrityError — the caller gets a clear message, and a real integrity fault stays a fault.
    _task(ledger)
    res = _resolver(ledger)
    res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="first")
    with pytest.raises(GovernanceError, match="pending gate"):
        res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="second")


# -- acceptance gate --------------------------------------------------------------------------------


def test_acceptance_approve_marks_done_and_fires_dependents(ledger: Ledger) -> None:
    _task(ledger, uid("t1"))
    ledger.tasks.submit(Task(id=uid("t2"), intent="depends", assignee_employee_id="alice"))
    ledger.dependencies.add(uid("t2"), uid("t1"))  # t2 depends on t1
    res = _resolver(ledger)
    approval = res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off")

    outcome = res.resolve_authenticated(
        approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
    )

    assert isinstance(outcome, ResolveOutcome)
    assert outcome.decision is ApprovalStatus.APPROVED
    assert outcome.subject_status == TaskStatus.DONE.value
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]
    assert outcome.wakes_fired == 1  # deps_resolved for t2
    assert any(w.payload.get("task_id") == uid("t2") for w in ledger.wakes.queued())


def test_acceptance_deny_stays_blocked_and_records_failed(ledger: Ledger) -> None:
    _task(ledger, uid("t1"))
    ledger.dod.create(uid("t1"), Verifier.human_approval())
    res = _resolver(ledger)
    approval = res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off")

    outcome = res.resolve_authenticated(
        approval.id, decision=ApprovalDecision.DENY, authorization=_authorization()
    )

    assert outcome.decision is ApprovalStatus.DENIED
    assert outcome.subject_status == TaskStatus.BLOCKED.value
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
    assert ledger.dod.get_for_task(uid("t1")).status is DodStatus.FAILED  # type: ignore[union-attr]


# -- authorization gate -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "decision",
    [
        ApprovalDecision.APPROVE,
        ApprovalDecision.DENY,
        ApprovalDecision.REQUEST_REVISION,
    ],
)
def test_legacy_human_acceptance_resolution_fails_closed(
    ledger: Ledger, decision: ApprovalDecision
) -> None:
    _task(ledger, uid("t1"))
    ledger.dod.create(uid("t1"), Verifier.human_approval())
    res = _resolver(ledger)
    approval = res.open_task_gate(
        uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="human sign-off"
    )

    with pytest.raises(GovernanceError, match="requires authenticated"):
        res.resolve(approval.id, decision=decision, decided_by_user_id=_USER, now=_NOW)

    persisted = ledger.approvals.get(approval.id)
    assert persisted is not None and persisted.status is ApprovalStatus.PENDING
    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.status is TaskStatus.BLOCKED
    assert res.get_authorization_proof(approval.id) is None


def test_legacy_authorization_approve_fails_closed(ledger: Ledger) -> None:
    _task(ledger, uid("t1"), assignee="alice")
    res = _resolver(ledger)
    approval = res.open_task_gate(
        uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="board sign-off"
    )

    with pytest.raises(GovernanceError, match="requires authenticated"):
        res.resolve(
            approval.id, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )

    task = ledger.tasks.get(uid("t1"))
    assert task is not None and task.status is TaskStatus.BLOCKED
    assert ledger.wakes.queued() == []


def test_authorization_approve_without_assignee_fires_no_wake(ledger: Ledger) -> None:
    _task(ledger, uid("t1"), assignee=None)
    res = _resolver(ledger)
    approval = res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="x")
    outcome = res.resolve_authenticated(
        approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
    )
    assert outcome.subject_status == TaskStatus.TODO.value and outcome.wakes_fired == 0


def test_authorization_deny_cancels(ledger: Ledger) -> None:
    _task(ledger, uid("t1"))
    res = _resolver(ledger)
    approval = res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="x")

    outcome = res.resolve_authenticated(
        approval.id, decision=ApprovalDecision.DENY, authorization=_authorization()
    )

    assert outcome.subject_status == TaskStatus.CANCELLED.value
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.CANCELLED  # type: ignore[union-attr]


# -- errors -----------------------------------------------------------------------------------------


def test_resolve_unknown_errors(ledger: Ledger) -> None:
    with pytest.raises(GovernanceError):
        _resolver(ledger).resolve(
            uid("ghost"), decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )


def test_resolve_already_decided_errors(ledger: Ledger) -> None:
    _task(ledger, uid("t1"))
    res = _resolver(ledger)
    approval = res.open_task_gate(uid("t1"), gate_kind=ApprovalGate.AUTHORIZATION, reason="x")
    res.resolve_authenticated(
        approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
    )
    with pytest.raises(GovernanceError):
        res.resolve(
            approval.id, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )


def test_resolve_non_task_subject_errors(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"),
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id=uid("bi1"),
            reason="hard cap",
        )
    )
    with pytest.raises(GovernanceError):
        _resolver(ledger).resolve(
            uid("a1"), decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )


def test_resolve_task_gate_without_kind_errors(ledger: Ledger) -> None:
    _task(ledger, uid("t1"))
    ledger.approvals.request(  # a task approval opened without a gate_kind (defensive)
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="x"
        )
    )
    with pytest.raises(GovernanceError):
        _resolver(ledger).resolve(
            uid("a1"), decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
        )
