"""Two-connection races around strict acceptance CAS and fail-closed newest recheck."""

from __future__ import annotations

import threading
import uuid
from datetime import UTC, datetime

import pytest

from chorus.governance import (
    ApprovalDecision,
    GovernanceError,
    GovernanceResolver,
    HumanAuthorization,
)
from chorus.ledger import (
    ApprovalGate,
    ApprovalStatus,
    Artifact,
    ArtifactType,
    AuthenticationMethod,
    DodStatus,
    Ledger,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    judge_task_finalization,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
_USER = "operator"


def _authorization() -> HumanAuthorization:
    return HumanAuthorization(
        decision_id=uid("decision"),
        user_id=_USER,
        method=AuthenticationMethod.SESSION,
        authenticated_at=_NOW,
        nonce=uid("nonce"),
        decided_at=_NOW,
        request_id="acceptance-cas",
        request_hash="sha256:acceptance-cas",
    )


def _open_pair(pg_database: str) -> tuple[Ledger, Ledger]:
    company_id = str(uuid.uuid4())
    return (
        Ledger.open(pg_database, company_id=company_id),
        Ledger.open(pg_database, company_id=company_id),
    )


def _seed_strict(ledger: Ledger, *, artifact_id: str = uid("art1")) -> None:
    ledger.employees.create(Employee(id="alice", name="alice", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("t1"),
            intent="ship",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="alice",
        )
    )
    ledger.dod.create(uid("t1"), Verifier.human_approval())
    ledger.artifacts.create(
        Artifact(
            id=artifact_id,
            task_id=uid("t1"),
            type=ArtifactType.DOC,
            review_state="pending",
            is_primary=True,
            resource_ref={"path": "spec.md"},
        )
    )
    ledger.runs.create(Run(id=uid("run-ok"), employee_id="alice", task_id=uid("t1")))
    ledger.runs.finish(uid("run-ok"), RunStatus.SUCCEEDED)


def test_newer_landing_during_approval_rolls_back_gate_stamp_and_finalization(
    pg_database: str,
) -> None:
    ledger, racer = _open_pair(pg_database)
    try:
        _seed_strict(ledger)
        resolver = GovernanceResolver(ledger)
        approval = resolver.open_task_gate(
            uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off"
        )
        original = ledger.artifacts.mark_latest_pending_primary_non_verdict_verified

        def mark_then_land_newer(task_id: str) -> Artifact | None:
            stamped = original(task_id)
            racer.artifacts.create(
                Artifact(
                    id=uid("art-newer"),
                    task_id=task_id,
                    type=ArtifactType.DOC,
                    review_state="pending",
                    is_primary=True,
                    resource_ref={"path": "newer.md"},
                )
            )
            return stamped

        ledger.artifacts.mark_latest_pending_primary_non_verdict_verified = mark_then_land_newer

        with pytest.raises(GovernanceError, match="stale primary"):
            resolver.resolve_authenticated(
                approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
            )

        kept = ledger.approvals.get(approval.id)
        assert kept is not None and kept.status is ApprovalStatus.PENDING
        assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
        original_artifact = ledger.artifacts.get(uid("art1"))
        newer = ledger.artifacts.get(uid("art-newer"))
        assert original_artifact is not None and original_artifact.review_state == "pending"
        assert original_artifact.resource_ref == {"path": "spec.md"}
        assert newer is not None and newer.review_state == "pending"
        assert newer.resource_ref == {"path": "newer.md"}
        dod = ledger.dod.get_for_task(uid("t1"))
        assert dod is not None and dod.status is DodStatus.PENDING
        assert judge_task_finalization(ledger, uid("t1")).passed is False
    finally:
        ledger.close()
        racer.close()


def test_lost_cas_second_connection_is_idempotent(pg_database: str) -> None:
    ledger, racer = _open_pair(pg_database)
    try:
        _seed_strict(ledger)
        lost: list[Artifact | None] = []

        def compete() -> None:
            lost.append(racer.artifacts.mark_latest_pending_primary_non_verdict_verified(uid("t1")))

        worker = threading.Thread(target=compete)
        with ledger.transaction():
            first = ledger.artifacts.mark_latest_pending_primary_non_verdict_verified(uid("t1"))
            worker.start()
            worker.join(timeout=0.3)
        worker.join(timeout=5)
        assert first is not None and first.review_state == "verified"
        assert first.resource_ref == {"path": "spec.md"}
        assert lost == [None]
        kept = ledger.artifacts.get(uid("art1"))
        assert kept is not None and kept.review_state == "verified"
        assert kept.resource_ref == {"path": "spec.md"}
        assert racer.artifacts.get(uid("art1")) == kept
    finally:
        ledger.close()
        racer.close()


def test_re_resolve_after_success_fails_closed_without_rewriting_rows(
    pg_database: str,
) -> None:
    ledger, racer = _open_pair(pg_database)
    try:
        _seed_strict(ledger)
        resolver = GovernanceResolver(ledger)
        approval = resolver.open_task_gate(
            uid("t1"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign off"
        )
        outcome = resolver.resolve_authenticated(
            approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
        )
        assert outcome.subject_status == TaskStatus.DONE.value
        verified = ledger.artifacts.get(uid("art1"))
        assert verified is not None and verified.review_state == "verified"

        with pytest.raises(GovernanceError, match="already"):
            resolver.resolve(
                approval.id, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
            )
        with pytest.raises(GovernanceError, match="already"):
            GovernanceResolver(racer).resolve(
                approval.id, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
            )

        kept = ledger.artifacts.get(uid("art1"))
        assert kept is not None
        assert kept.review_state == "verified"
        assert kept.resource_ref == {"path": "spec.md"}
        assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]
        assert judge_task_finalization(ledger, uid("t1")).passed is True
        assert judge_task_finalization(racer, uid("t1")).passed is True
    finally:
        ledger.close()
        racer.close()
