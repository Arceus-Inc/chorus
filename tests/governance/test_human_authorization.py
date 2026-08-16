"""Authenticated terminal approval resolution carries immutable human evidence."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, timezone

import pytest

from chorus.events import Event
from chorus.governance import (
    ActionOutcome,
    ApprovalDecision,
    GovernanceError,
    GovernanceRegistry,
    GovernanceResolver,
    HumanAuthorization,
)
from chorus.governance._actions import TaskGateAction
from chorus.ledger import (
    ActivityVerb,
    Approval,
    ApprovalGate,
    ApprovalStatus,
    Artifact,
    ArtifactType,
    AuthenticationMethod,
    AuthorizationVerdict,
    HumanAuthorizationProof,
    Ledger,
    LedgerIntegrityError,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_AUTHENTICATED_AT = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)
_DECIDED_AT = datetime(2026, 8, 9, 9, 1, tzinfo=UTC)


def _task(ledger: Ledger, task_id: str) -> None:
    if ledger.employees.get("ada") is None:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=task_id,
            intent="review me",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
        )
    )


def _authorization(
    *,
    nonce: str | None = None,
    decision_id: str | None = None,
    authenticated_at: datetime = _AUTHENTICATED_AT,
    decided_at: datetime = _DECIDED_AT,
) -> HumanAuthorization:
    return HumanAuthorization(
        decision_id=decision_id or uid("decision"),
        user_id="operator",
        method=AuthenticationMethod.STEP_UP,
        authenticated_at=authenticated_at,
        nonce=nonce or uid("nonce"),
        decided_at=decided_at,
        request_id="request-trace-123",
        request_hash="sha256:canonical-request-body",
    )


def _opened_gate(ledger: Ledger, task_id: str) -> tuple[GovernanceResolver, str]:
    _task(ledger, task_id)
    resolver = GovernanceResolver(ledger)
    approval = resolver.open_task_gate(
        task_id, gate_kind=ApprovalGate.AUTHORIZATION, reason="human sign-off"
    )
    return resolver, approval.id


def test_authenticated_resolution_persists_typed_immutable_proof(ledger: Ledger) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))
    authorization = _authorization()

    outcome = resolver.resolve_authenticated(
        approval_id, decision=ApprovalDecision.APPROVE, authorization=authorization
    )

    proof = resolver.get_authorization_proof(approval_id)
    assert proof is not None
    assert proof.decision_id == authorization.decision_id
    assert proof.approval_id == approval_id
    assert proof.user_id == authorization.user_id
    assert proof.method is AuthenticationMethod.STEP_UP
    assert proof.authenticated_at == _AUTHENTICATED_AT
    assert proof.nonce == authorization.nonce
    assert proof.decided_at == _DECIDED_AT
    assert proof.request_id == authorization.request_id
    assert proof.request_hash == authorization.request_hash
    assert proof.verdict is AuthorizationVerdict.APPROVE
    assert resolver.get_authorization_proof_by_nonce(authorization.nonce) == proof
    assert outcome.decision is ApprovalStatus.APPROVED
    approval = ledger.approvals.get(approval_id)
    assert approval is not None
    assert approval.decided_by_user_id == authorization.user_id
    assert approval.decided_at == authorization.decided_at


class _FailingEventSink:
    def emit(self, event: Event) -> None:
        del event
        raise RuntimeError("event delivery unavailable")


def test_live_event_failure_returns_committed_replayable_landed_outcome(
    ledger: Ledger,
    caplog: pytest.LogCaptureFixture,
) -> None:
    task_id = uid("human-acceptance")
    _task(ledger, task_id)
    ledger.dod.create(task_id, Verifier.human_approval())
    ledger.artifacts.create(
        Artifact(
            id=uid("art"),
            task_id=task_id,
            type=ArtifactType.DOC,
            review_state="pending",
            is_primary=True,
            resource_ref={"path": "spec.md"},
        )
    )
    ledger.runs.create(Run(id=uid("run-ok"), employee_id="ada", task_id=task_id))
    ledger.runs.finish(uid("run-ok"), RunStatus.SUCCEEDED)
    resolver = GovernanceResolver(ledger, event_sink=_FailingEventSink())
    approval = resolver.open_task_gate(
        task_id,
        gate_kind=ApprovalGate.ACCEPTANCE,
        reason="human acceptance",
    )

    with caplog.at_level(logging.WARNING, logger="chorus.governance.resolver"):
        outcome = resolver.resolve_authenticated(
            approval.id,
            decision=ApprovalDecision.APPROVE,
            authorization=_authorization(),
        )

    assert outcome.landed is not None and outcome.landed.phase.value == "terminal_pass"
    assert resolver.get_landed_outcome(approval.id) == outcome.landed
    persisted = ledger.approvals.get(approval.id)
    assert persisted is not None and persisted.status is ApprovalStatus.APPROVED
    assert resolver.get_authorization_proof(approval.id) is not None
    durable = [
        row
        for row in ledger.activity.by_subject("approval", approval.id)
        if row.verb is ActivityVerb.OUTCOME_LANDED
    ]
    assert len(durable) == 1
    assert "durable receipt remains" in caplog.text


def test_duplicate_nonce_rejects_and_rolls_back_second_resolution(ledger: Ledger) -> None:
    resolver, first_approval_id = _opened_gate(ledger, uid("first"))
    nonce = uid("idem")
    resolver.resolve_authenticated(
        first_approval_id,
        decision=ApprovalDecision.APPROVE,
        authorization=_authorization(nonce=nonce),
    )
    _, second_approval_id = _opened_gate(ledger, uid("second"))

    with pytest.raises(LedgerIntegrityError):
        resolver.resolve_authenticated(
            second_approval_id,
            decision=ApprovalDecision.APPROVE,
            authorization=_authorization(nonce=nonce, decision_id=uid("second-decision")),
        )

    second = ledger.approvals.get(second_approval_id)
    assert second is not None
    assert second.status is ApprovalStatus.PENDING
    assert resolver.get_authorization_proof(second_approval_id) is None
    task = ledger.tasks.get(uid("second"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


def test_authenticated_holds_stay_pending_then_terminal_approval_resolves(ledger: Ledger) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))
    hold = resolver.hold_authenticated(approval_id, authorization=_authorization())
    second_hold = resolver.hold_authenticated(
        approval_id,
        authorization=_authorization(
            nonce=uid("second-hold-nonce"),
            decision_id=uid("second-hold-decision"),
            decided_at=_DECIDED_AT + timedelta(seconds=1),
        ),
    )

    pending = ledger.approvals.get(approval_id)
    assert pending is not None
    assert pending.status is ApprovalStatus.PENDING
    blocked = ledger.tasks.get(uid("task"))
    assert blocked is not None
    assert blocked.status is TaskStatus.BLOCKED
    assert hold.verdict is AuthorizationVerdict.HOLD
    assert [activity.verb for activity in ledger.activity.by_subject("task", uid("task"))] == [
        ActivityVerb.GATED,
        ActivityVerb.HELD,
        ActivityVerb.HELD,
    ]

    resolver.resolve_authenticated(
        approval_id,
        decision=ApprovalDecision.APPROVE,
        authorization=_authorization(
            nonce=uid("terminal-nonce"),
            decision_id=uid("terminal-decision"),
            decided_at=_DECIDED_AT + timedelta(seconds=2),
        ),
    )

    terminal = resolver.get_authorization_proof(approval_id)
    assert terminal is not None
    assert terminal.verdict is AuthorizationVerdict.APPROVE
    assert [proof.verdict for proof in resolver.get_authorization_proofs(approval_id)] == [
        AuthorizationVerdict.HOLD,
        AuthorizationVerdict.HOLD,
        AuthorizationVerdict.APPROVE,
    ]
    assert second_hold.verdict is AuthorizationVerdict.HOLD
    resolved = ledger.approvals.get(approval_id)
    assert resolved is not None
    assert resolved.status is ApprovalStatus.APPROVED


def test_duplicate_terminal_resolution_leaves_existing_proof_and_status_intact(
    ledger: Ledger,
) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))
    resolver.resolve_authenticated(
        approval_id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
    )

    with pytest.raises(GovernanceError, match="already"):
        resolver.resolve_authenticated(
            approval_id,
            decision=ApprovalDecision.DENY,
            authorization=_authorization(
                nonce=uid("second-nonce"), decision_id=uid("second-decision")
            ),
        )

    proofs = resolver.get_authorization_proofs(approval_id)
    assert [proof.verdict for proof in proofs] == [AuthorizationVerdict.APPROVE]
    approval = ledger.approvals.get(approval_id)
    assert approval is not None
    assert approval.status is ApprovalStatus.APPROVED


def test_database_enforces_terminal_verdict_consistency_and_proof_immutability(
    ledger: Ledger,
) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))
    inconsistent = HumanAuthorizationProof(
        decision_id=uid("inconsistent-decision"),
        approval_id=approval_id,
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT,
        nonce=uid("inconsistent-nonce"),
        decided_at=_DECIDED_AT,
        request_id="request-trace-123",
        request_hash="sha256:canonical-request-body",
        verdict=AuthorizationVerdict.DENY,
    )
    with pytest.raises(Exception, match="verdict does not match"):
        with ledger.transaction():
            assert ledger.approvals.set_status(
                approval_id,
                ApprovalStatus.APPROVED,
                decided_by_user_id="operator",
                decided_at=_DECIDED_AT,
            )
            ledger.human_authorization_proofs.record(inconsistent)

    pending = ledger.approvals.get(approval_id)
    assert pending is not None
    assert pending.status is ApprovalStatus.PENDING

    consistent = HumanAuthorizationProof(
        decision_id=uid("consistent-decision"),
        approval_id=approval_id,
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT,
        nonce=uid("consistent-nonce"),
        decided_at=_DECIDED_AT,
        request_id="request-trace-456",
        request_hash="sha256:original-body",
        verdict=AuthorizationVerdict.APPROVE,
    )
    with ledger.transaction():
        assert ledger.approvals.set_status(
            approval_id,
            ApprovalStatus.APPROVED,
            decided_by_user_id="operator",
            decided_at=_DECIDED_AT,
        )
        ledger.human_authorization_proofs.record(consistent)

    with pytest.raises(Exception, match="immutable"):
        ledger._conn.execute(
            "UPDATE human_authorization_proof SET request_hash = ? WHERE approval_id = ?",
            ("sha256:rewritten-body", approval_id),
        )

    persisted = resolver.get_authorization_proof(approval_id)
    assert persisted is not None
    assert persisted.request_hash == "sha256:original-body"


def test_direct_repo_status_bypass_fails_at_commit_without_terminal_proof(ledger: Ledger) -> None:
    _, approval_id = _opened_gate(ledger, uid("task"))

    with pytest.raises(Exception, match="matching terminal proof"):
        ledger.approvals.set_status(
            approval_id,
            ApprovalStatus.APPROVED,
            decided_by_user_id="operator",
            decided_at=_DECIDED_AT,
        )

    pending = ledger.approvals.get(approval_id)
    assert pending is not None
    assert pending.status is ApprovalStatus.PENDING
    assert ledger.human_authorization_proofs.get(approval_id) is None
    task = ledger.tasks.get(uid("task"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


def test_acceptance_gate_still_resolves_without_an_authorization_proof(ledger: Ledger) -> None:
    _task(ledger, uid("task"))
    approval = GovernanceResolver(ledger).open_task_gate(
        uid("task"), gate_kind=ApprovalGate.ACCEPTANCE, reason="sign-off"
    )
    assert ledger.approvals.set_status(
        approval.id,
        ApprovalStatus.APPROVED,
        decided_by_user_id="operator",
        decided_at=_DECIDED_AT,
    )
    got = ledger.approvals.get(approval.id)
    assert got is not None and got.status is ApprovalStatus.APPROVED
    assert ledger.human_authorization_proofs.get(approval.id) is None


def test_record_returns_the_inserted_decision_row(ledger: Ledger) -> None:
    _, approval_id = _opened_gate(ledger, uid("task"))
    newer = HumanAuthorizationProof(
        decision_id=uid("newer-hold"),
        approval_id=approval_id,
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT,
        nonce=uid("newer-nonce"),
        decided_at=_DECIDED_AT + timedelta(seconds=1),
        request_id="request-trace-newer",
        request_hash="sha256:newer-hold",
        verdict=AuthorizationVerdict.HOLD,
    )
    older = HumanAuthorizationProof(
        decision_id=uid("older-hold"),
        approval_id=approval_id,
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT,
        nonce=uid("older-nonce"),
        decided_at=_DECIDED_AT,
        request_id="request-trace-older",
        request_hash="sha256:older-hold",
        verdict=AuthorizationVerdict.HOLD,
    )

    recorded_newer = ledger.human_authorization_proofs.record(newer)
    recorded_older = ledger.human_authorization_proofs.record(older)

    assert recorded_newer.decision_id == newer.decision_id
    assert recorded_older.decision_id == older.decision_id
    assert recorded_older.nonce == older.nonce
    latest = ledger.human_authorization_proofs.get(approval_id)
    assert latest is not None
    assert latest.decision_id == newer.decision_id
    assert recorded_older.decision_id != latest.decision_id


def test_authenticated_resolution_refuses_an_already_decided_approval(ledger: Ledger) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))
    resolver.resolve_authenticated(
        approval_id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
    )

    with pytest.raises(GovernanceError, match="already"):
        resolver.resolve_authenticated(
            approval_id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
        )

    proof = resolver.get_authorization_proof(approval_id)
    assert proof is not None
    assert proof.verdict is AuthorizationVerdict.APPROVE


class _FailingTaskGateAction(TaskGateAction):
    def on_approve(self, approval: Approval) -> ActionOutcome:
        super().on_approve(approval)
        raise RuntimeError("handler failed after its side effect")


def test_handler_failure_rolls_back_proof_status_and_handler_side_effect(ledger: Ledger) -> None:
    _task(ledger, uid("task"))
    resolver = GovernanceResolver(
        ledger, GovernanceRegistry.from_actions([_FailingTaskGateAction(ledger)])
    )
    approval = resolver.open_task_gate(
        uid("task"), gate_kind=ApprovalGate.AUTHORIZATION, reason="human sign-off"
    )

    with pytest.raises(RuntimeError, match="handler failed"):
        resolver.resolve_authenticated(
            approval.id, decision=ApprovalDecision.APPROVE, authorization=_authorization()
        )

    unresolved = ledger.approvals.get(approval.id)
    assert unresolved is not None
    assert unresolved.status is ApprovalStatus.PENDING
    assert resolver.get_authorization_proof(approval.id) is None
    task = ledger.tasks.get(uid("task"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


def test_human_authorization_proof_survives_a_ledger_restart(pg_database: str) -> None:
    company_id = uid("company")
    ledger = Ledger.open(pg_database, company_id=company_id)
    authorization = _authorization()
    try:
        resolver, approval_id = _opened_gate(ledger, uid("task"))
        resolver.resolve_authenticated(
            approval_id, decision=ApprovalDecision.APPROVE, authorization=authorization
        )
    finally:
        ledger.close()

    reopened = Ledger.open(pg_database, company_id=company_id)
    try:
        proof = GovernanceResolver(reopened).get_authorization_proof(approval_id)
        assert proof is not None
        assert proof.decision_id == authorization.decision_id
        assert proof.request_hash == authorization.request_hash
    finally:
        reopened.close()


def test_human_authorization_proof_isolated_by_company(pg_database: str) -> None:
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chorus_auth_app') "
            "THEN CREATE ROLE chorus_auth_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_auth_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO chorus_auth_app"
        )
    app_conninfo = pg_database.replace("user=postgres", "user=chorus_auth_app")
    ledger_a = Ledger.open(app_conninfo, company_id=uid("company-a"))
    ledger_b = Ledger.open(app_conninfo, company_id=uid("company-b"))
    nonce = uid("shared-idempotency-key")
    try:
        resolver_a, approval_a = _opened_gate(ledger_a, uid("task-a"))
        auth_a = _authorization(nonce=nonce, decision_id=uid("decision-a"))
        resolver_a.resolve_authenticated(
            approval_a, decision=ApprovalDecision.APPROVE, authorization=auth_a
        )
        proof_a = resolver_a.get_authorization_proof(approval_a)
        assert proof_a is not None
        assert proof_a.decision_id == auth_a.decision_id
        resolver_b, approval_b = _opened_gate(ledger_b, uid("task-b"))
        auth_b = _authorization(nonce=nonce, decision_id=uid("decision-b"))
        resolver_b.resolve_authenticated(
            approval_b,
            decision=ApprovalDecision.APPROVE,
            authorization=auth_b,
        )

        assert resolver_b.get_authorization_proof(approval_a) is None
        proof_b = resolver_b.get_authorization_proof_by_nonce(nonce)
        assert proof_b is not None
        assert proof_b.approval_id == approval_b
        assert proof_b.decision_id == auth_b.decision_id
        assert proof_b.decision_id != proof_a.decision_id
    finally:
        ledger_a.close()
        ledger_b.close()


def test_human_authorization_rejects_non_utc_timestamps() -> None:
    with pytest.raises(ValueError, match="UTC"):
        HumanAuthorization(
            decision_id=uid("decision"),
            user_id="operator",
            method=AuthenticationMethod.SESSION,
            authenticated_at=_AUTHENTICATED_AT.astimezone(timezone(timedelta(hours=5, minutes=30))),
            nonce=uid("nonce"),
            decided_at=_DECIDED_AT,
            request_id="request-trace-123",
            request_hash="sha256:canonical-request-body",
        )
    with pytest.raises(ValueError, match="UTC"):
        HumanAuthorization(
            decision_id=uid("naive-decision"),
            user_id="operator",
            method=AuthenticationMethod.SESSION,
            authenticated_at=datetime(2026, 8, 9, 9, 0),
            nonce=uid("naive-nonce"),
            decided_at=_DECIDED_AT,
            request_id="request-trace-123",
            request_hash="sha256:canonical-request-body",
        )


def test_human_authorization_normalizes_zero_offset_to_datetime_utc() -> None:
    zero_offset = timezone(timedelta(0))
    authorization = HumanAuthorization(
        decision_id=uid("decision"),
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT.astimezone(zero_offset),
        nonce=uid("nonce"),
        decided_at=_DECIDED_AT.astimezone(zero_offset),
        request_id="request-trace-123",
        request_hash="sha256:canonical-request-body",
    )
    assert authorization.authenticated_at.tzinfo is UTC
    assert authorization.decided_at.tzinfo is UTC
    proof = HumanAuthorizationProof(
        decision_id=uid("proof-decision"),
        approval_id=uid("approval"),
        user_id="operator",
        method=AuthenticationMethod.SESSION,
        authenticated_at=_AUTHENTICATED_AT.astimezone(zero_offset),
        nonce=uid("proof-nonce"),
        decided_at=_DECIDED_AT.astimezone(zero_offset),
        request_id="request-trace-123",
        request_hash="sha256:canonical-request-body",
        verdict=AuthorizationVerdict.HOLD,
    )
    assert proof.authenticated_at.tzinfo is UTC
    assert proof.decided_at.tzinfo is UTC


def test_human_authorization_rejects_authentication_after_decision() -> None:
    with pytest.raises(ValueError, match="authenticated_at"):
        _authorization(authenticated_at=_DECIDED_AT + timedelta(seconds=1))
    with pytest.raises(ValueError, match="authenticated_at"):
        HumanAuthorizationProof(
            decision_id=uid("late-decision"),
            approval_id=uid("approval"),
            user_id="operator",
            method=AuthenticationMethod.SESSION,
            authenticated_at=_DECIDED_AT + timedelta(seconds=1),
            nonce=uid("late-nonce"),
            decided_at=_DECIDED_AT,
            request_id="request-trace-123",
            request_hash="sha256:canonical-request-body",
            verdict=AuthorizationVerdict.HOLD,
        )


def test_set_status_requires_utc_decided_at(ledger: Ledger) -> None:
    _, approval_id = _opened_gate(ledger, uid("task"))
    with pytest.raises(ValueError, match="UTC"):
        ledger.approvals.set_status(
            approval_id,
            ApprovalStatus.APPROVED,
            decided_by_user_id="operator",
            decided_at=datetime(2026, 8, 9, 9, 1),
        )
    pending = ledger.approvals.get(approval_id)
    assert pending is not None
    assert pending.status is ApprovalStatus.PENDING


def test_human_authorization_rejects_blank_evidence_fields() -> None:
    with pytest.raises(ValueError, match="must not be blank"):
        HumanAuthorization(
            decision_id=uid("decision"),
            user_id="   ",
            method=AuthenticationMethod.SESSION,
            authenticated_at=_AUTHENTICATED_AT,
            nonce=uid("nonce"),
            decided_at=_DECIDED_AT,
            request_id="request-trace-123",
            request_hash="sha256:canonical-request-body",
        )
    with pytest.raises(ValueError, match="must not be blank"):
        HumanAuthorizationProof(
            decision_id=uid("blank-decision"),
            approval_id=uid("approval"),
            user_id="operator",
            method=AuthenticationMethod.SESSION,
            authenticated_at=_AUTHENTICATED_AT,
            nonce=" ",
            decided_at=_DECIDED_AT,
            request_id="request-trace-123",
            request_hash="sha256:canonical-request-body",
            verdict=AuthorizationVerdict.HOLD,
        )


def test_database_rejects_authentication_after_decision(ledger: Ledger) -> None:
    resolver, approval_id = _opened_gate(ledger, uid("task"))

    with pytest.raises(Exception, match="authenticated_at"):
        ledger._conn.execute(
            "INSERT INTO human_authorization_proof "
            "(decision_id, approval_id, user_id, method, authenticated_at, nonce, decided_at, "
            "request_id, request_hash, verdict) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uid("late-decision"),
                approval_id,
                "operator",
                AuthenticationMethod.SESSION.value,
                (_DECIDED_AT + timedelta(seconds=1)).isoformat(),
                uid("late-nonce"),
                _DECIDED_AT.isoformat(),
                "request-trace-123",
                "sha256:canonical-request-body",
                AuthorizationVerdict.HOLD.value,
            ),
        )

    assert resolver.get_authorization_proof(approval_id) is None
