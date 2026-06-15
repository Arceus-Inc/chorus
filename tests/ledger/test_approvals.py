"""ApprovalRepo — the human gate (spec 01 Cluster G ``approval``, spec 04 §5).

A task that needs sign-off sits ``blocked`` while an ``approval`` row holds the verdict a human (or
horizon, later) resolves. The gate is exact-once: at most one *pending* approval per subject
(partial-unique index). ``approve`` / ``deny`` stamp the decider and timestamp.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger import Approval, ApprovalStatus, ApprovalSubjectKind, SqliteLedger

pytestmark = pytest.mark.integration


def test_request_and_get(ledger: SqliteLedger) -> None:
    req = ledger.approvals.request(
        Approval(
            id="a1",
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id="bi1",
            reason="hard cap breached",
        )
    )
    got = ledger.approvals.get(req.id)
    assert got is not None
    assert got.subject_kind is ApprovalSubjectKind.BUDGET_INCIDENT
    assert got.subject_id == "bi1"
    assert got.status is ApprovalStatus.PENDING
    assert got.decided_by_user_id is None
    assert got.created_at is not None


def test_approve_stamps_decider(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="gate")
    )
    ledger.approvals.approve("a1", decided_by_user_id="u1")
    got = ledger.approvals.get("a1")
    assert got is not None
    assert got.status is ApprovalStatus.APPROVED
    assert got.decided_by_user_id == "u1"
    assert got.decided_at is not None


def test_deny_stamps_decider(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="gate")
    )
    ledger.approvals.deny("a1", decided_by_user_id="u2")
    got = ledger.approvals.get("a1")
    assert got is not None
    assert got.status is ApprovalStatus.DENIED
    assert got.decided_by_user_id == "u2"
    assert got.decided_at is not None


def test_pending_lists_only_open(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="x")
    )
    ledger.approvals.request(
        Approval(id="a2", subject_kind=ApprovalSubjectKind.TASK, subject_id="t2", reason="y")
    )
    ledger.approvals.approve("a1", decided_by_user_id="u1")
    assert [a.id for a in ledger.approvals.pending()] == ["a2"]


def test_at_most_one_pending_per_subject(ledger: SqliteLedger) -> None:
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="x")
    )
    with pytest.raises(sqlite3.IntegrityError):
        ledger.approvals.request(
            Approval(id="a2", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="dup")
        )


def test_resolved_subject_can_be_re_requested(ledger: SqliteLedger) -> None:
    # once a gate is resolved, the partial-unique index frees the subject for a fresh gate
    ledger.approvals.request(
        Approval(id="a1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="x")
    )
    ledger.approvals.deny("a1", decided_by_user_id="u1")
    again = ledger.approvals.request(
        Approval(id="a2", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="retry")
    )
    assert again.status is ApprovalStatus.PENDING
