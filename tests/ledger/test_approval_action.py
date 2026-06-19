"""approval.action — the governed-action column (§5 governance, Approach A).

Every ``approval`` names which governed action it is (``ApprovalAction``); the resolver dispatches on
it. ``action`` round-trips through the repo and defaults to ``task_gate`` for backward construction;
``set_status`` generalises approve/deny to also carry the third resolution ``revision_requested``.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalStatus,
    ApprovalSubjectKind,
    SqliteLedger,
)

pytestmark = pytest.mark.integration


def test_action_round_trips(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(
            id="a1",
            subject_kind=ApprovalSubjectKind.EMPLOYEE,
            subject_id="emp1",
            reason="hire the engineer",
            action=ApprovalAction.HIRE_EMPLOYEE,
        )
    )
    got = ledger.approvals.get("a1")
    assert got is not None and got.action is ApprovalAction.HIRE_EMPLOYEE


def test_action_defaults_to_task_gate(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="x")
    )
    got = ledger.approvals.get("a1")
    assert got is not None and got.action is ApprovalAction.TASK_GATE


def test_set_status_records_revision_requested(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(
            id="a1",
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id="t1",
            reason="re-plan it",
            action=ApprovalAction.PLAN_APPROVAL,
        )
    )
    ledger.approvals.set_status(
        "a1", ApprovalStatus.REVISION_REQUESTED, decided_by_user_id="u1"
    )
    got = ledger.approvals.get("a1")
    assert got is not None
    assert got.status is ApprovalStatus.REVISION_REQUESTED
    assert got.decided_by_user_id == "u1"
    assert got.decided_at is not None


def test_revision_requested_frees_the_subject_gate(ledger: SqliteLedger) -> None:
    # a resolved (revision_requested) gate no longer holds the subject's exact-once pending slot.
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="x")
    )
    ledger.approvals.set_status("a1", ApprovalStatus.REVISION_REQUESTED, decided_by_user_id="u1")
    assert ledger.approvals.pending() == []  # not pending anymore
