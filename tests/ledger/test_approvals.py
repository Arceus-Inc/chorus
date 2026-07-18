"""ApprovalRepo — the human gate (spec 01 Cluster G ``approval``, spec 04 §5).

A task that needs sign-off sits ``blocked`` while an ``approval`` row holds the verdict a human (or
horizon, later) resolves. The gate is exact-once: at most one *pending* approval per subject
(partial-unique index). ``approve`` / ``deny`` stamp the decider and timestamp.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Approval,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    Ledger,
    LedgerIntegrityError,
)
from chorus.testing import uid

pytestmark = pytest.mark.integration


def test_gate_kind_round_trips(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t1"),
            reason="sign off the spec",
            gate_kind=ApprovalGate.ACCEPTANCE,
        )
    )
    got = ledger.approvals.get(uid("a1"))
    assert got is not None and got.gate_kind is ApprovalGate.ACCEPTANCE


def test_gate_kind_defaults_to_none(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"),
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id=uid("bi1"),
            reason="x",
        )
    )
    got = ledger.approvals.get(uid("a1"))
    assert got is not None and got.gate_kind is None


def test_request_and_get(ledger: Ledger) -> None:
    req = ledger.approvals.request(
        Approval(
            id=uid("a1"),
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id=uid("bi1"),
            reason="hard cap breached",
        )
    )
    got = ledger.approvals.get(req.id)
    assert got is not None
    assert got.subject_kind is ApprovalSubjectKind.BUDGET_INCIDENT
    assert got.subject_id == uid("bi1")
    assert got.status is ApprovalStatus.PENDING
    assert got.decided_by_user_id is None
    assert got.created_at is not None


def test_approve_stamps_decider(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="gate"
        )
    )
    ledger.approvals.approve(uid("a1"), decided_by_user_id=uid("u1"))
    got = ledger.approvals.get(uid("a1"))
    assert got is not None
    assert got.status is ApprovalStatus.APPROVED
    assert got.decided_by_user_id == uid("u1")
    assert got.decided_at is not None


def test_deny_stamps_decider(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="gate"
        )
    )
    ledger.approvals.deny(uid("a1"), decided_by_user_id=uid("u2"))
    got = ledger.approvals.get(uid("a1"))
    assert got is not None
    assert got.status is ApprovalStatus.DENIED
    assert got.decided_by_user_id == uid("u2")
    assert got.decided_at is not None


def test_pending_lists_only_open(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="x"
        )
    )
    ledger.approvals.request(
        Approval(
            id=uid("a2"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t2"), reason="y"
        )
    )
    ledger.approvals.approve(uid("a1"), decided_by_user_id=uid("u1"))
    assert [a.id for a in ledger.approvals.pending()] == [uid("a2")]


def test_at_most_one_pending_per_subject(ledger: Ledger) -> None:
    ledger.approvals.request(
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="x"
        )
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.approvals.request(
            Approval(
                id=uid("a2"),
                subject_kind=ApprovalSubjectKind.TASK,
                subject_id=uid("t1"),
                reason="dup",
            )
        )


def test_resolved_subject_can_be_re_requested(ledger: Ledger) -> None:
    # once a gate is resolved, the partial-unique index frees the subject for a fresh gate
    ledger.approvals.request(
        Approval(
            id=uid("a1"), subject_kind=ApprovalSubjectKind.TASK, subject_id=uid("t1"), reason="x"
        )
    )
    ledger.approvals.deny(uid("a1"), decided_by_user_id=uid("u1"))
    again = ledger.approvals.request(
        Approval(
            id=uid("a2"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t1"),
            reason="retry",
        )
    )
    assert again.status is ApprovalStatus.PENDING


def test_for_subject_lists_newest_first(ledger: Ledger) -> None:
    # Two resolved gates + one pending for the same subject; a stranger subject stays invisible.
    ledger.approvals.request(
        Approval(
            id=uid("a1"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t1"),
            reason="first",
        )
    )
    ledger.approvals.deny(uid("a1"), decided_by_user_id="boss")
    ledger.approvals.request(
        Approval(
            id=uid("a2"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t1"),
            reason="second",
        )
    )
    ledger.approvals.approve(uid("a2"), decided_by_user_id="boss")
    ledger.approvals.request(
        Approval(
            id=uid("zz"), subject_kind=ApprovalSubjectKind.TASK, subject_id="OTHER", reason="x"
        )
    )

    got = ledger.approvals.for_subject(uid("t1"))
    assert [a.id for a in got] == [uid("a2"), uid("a1")]  # newest first
    assert got[0].status is ApprovalStatus.APPROVED


def test_for_subject_empty_for_unknown_subject(ledger: Ledger) -> None:
    assert ledger.approvals.for_subject("ghost") == []
