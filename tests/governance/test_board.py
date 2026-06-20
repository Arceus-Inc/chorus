"""board_approval — promote a landed deliverable to the board (§5 governance, Approach A), e2e.

A landed artifact is gated for promotion. Approve records a ``promoted`` activity on it; deny does not
promote; revise wakes the artifact's author to revise. Driven through the real resolver + ledger, and
the facade's policy-gated ``request_promotion``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.facade import Caps, Chorus
from chorus.governance import ApprovalDecision, GovernancePolicy, GovernanceResolver
from chorus.ledger import (
    ActivityVerb,
    Approval,
    ApprovalAction,
    ApprovalSubjectKind,
    Artifact,
    ArtifactType,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "chair"


def _landed_artifact(ledger: SqliteLedger) -> str:
    ledger.employees.create(Employee(id="ada", name="ada", role="engineer"))
    ledger.tasks.submit(
        Task(id="t1", intent="ship the pr", status=TaskStatus.DONE, assignee_employee_id="ada")
    )
    ledger.artifacts.create(Artifact(id="ar1", task_id="t1", type=ArtifactType.PR))
    return "ar1"


def _open_board_gate(ledger: SqliteLedger, artifact_id: str) -> str:
    return GovernanceResolver(ledger).open(
        action=ApprovalAction.BOARD_APPROVAL,
        subject_kind=ApprovalSubjectKind.ARTIFACT,
        subject_id=artifact_id,
        reason="promote",
    ).id


def test_approve_records_a_promoted_activity(ledger: SqliteLedger) -> None:
    gate = _open_board_gate(ledger, _landed_artifact(ledger))

    outcome = GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
    )

    assert outcome.subject_status == "promoted"
    verbs = [a.verb for a in ledger.activity.by_subject("artifact", "ar1")]
    assert ActivityVerb.PROMOTED in verbs


def test_deny_does_not_promote(ledger: SqliteLedger) -> None:
    gate = _open_board_gate(ledger, _landed_artifact(ledger))

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.DENY, decided_by_user_id=_USER, now=_NOW
    )

    verbs = [a.verb for a in ledger.activity.by_subject("artifact", "ar1")]
    assert ActivityVerb.PROMOTED not in verbs


def test_revise_wakes_the_author(ledger: SqliteLedger) -> None:
    gate = _open_board_gate(ledger, _landed_artifact(ledger))

    outcome = GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.REQUEST_REVISION, decided_by_user_id=_USER, now=_NOW
    )

    assert outcome.subject_status == "revision"
    assert {w.employee_id for w in ledger.wakes.queued()} == {"ada"}


def test_resolve_unknown_action_subject_passes_through_dispatch(ledger: SqliteLedger) -> None:
    # a board_approval approval with no real artifact still resolves (revise just fires no wake).
    ledger.approvals.request(
        Approval(
            id="a1",
            subject_kind=ApprovalSubjectKind.ARTIFACT,
            subject_id="ghost",
            reason="x",
            action=ApprovalAction.BOARD_APPROVAL,
        )
    )
    outcome = GovernanceResolver(ledger).resolve(
        "a1", decision=ApprovalDecision.REQUEST_REVISION, decided_by_user_id=_USER, now=_NOW
    )
    assert outcome.wakes_fired == 0


# -- through the facade ------------------------------------------------------------------------------


def _chorus(ledger: SqliteLedger, policy: GovernancePolicy) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
        governance_policy=policy,
    )


def test_facade_request_promotion_gated_opens_a_board_gate(ledger: SqliteLedger) -> None:
    _landed_artifact(ledger)
    chorus = _chorus(ledger, GovernancePolicy(board_artifact_classes=frozenset({"pr"})))

    approval = chorus.governance.request_promotion("ar1")

    assert approval is not None and approval.action is ApprovalAction.BOARD_APPROVAL


def test_facade_request_promotion_ungated_returns_none(ledger: SqliteLedger) -> None:
    _landed_artifact(ledger)
    chorus = _chorus(ledger, GovernancePolicy())  # "pr" not in board classes

    assert chorus.governance.request_promotion("ar1") is None
    assert ledger.approvals.pending() == []
