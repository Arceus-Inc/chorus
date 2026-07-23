"""Regression tests for the codeant review consolidation (spec 01 hardening).

Each test pins a behaviour a code-review comment flagged across the spec-01 PRs: repo-layer lifecycle
guards, bounded counters, live-recompute hygiene, and the DB-level CHECK/FK invariants added in
migration 0013. Grouped by the table they harden.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.heartbeat import Wake
from chorus.ledger import (
    Approval,
    ApprovalSubjectKind,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    BudgetIncident,
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
    CostEvent,
    DecompositionClaim,
    Ledger,
    LedgerIntegrityError,
    Message,
    Monitor,
    Task,
    WakeReason,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str = uid("e1")) -> str:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    return eid


def _now() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


# --- wake (PR#6) ---------------------------------------------------------------------------------


def test_mark_done_ignores_queued_wakes(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(Wake(id=uid("w1"), employee_id=uid("e1"), reason=WakeReason.MANUAL))
    ledger.wakes.mark_done(uid("w1"))  # still queued, not claimed -> no-op
    got = ledger.wakes.get(uid("w1"))
    assert got is not None
    assert got.status.value == "queued"


def test_claim_then_mark_done_completes(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(Wake(id=uid("w1"), employee_id=uid("e1"), reason=WakeReason.MANUAL))
    ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(uid("w1"))
    got = ledger.wakes.get(uid("w1"))
    assert got is not None
    assert got.status.value == "done"


def test_claim_nonpositive_limit_is_empty(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(Wake(id=uid("w1"), employee_id=uid("e1"), reason=WakeReason.MANUAL))
    assert ledger.wakes.claim(limit=0) == []


# --- decomposition_claim (PR#11) -----------------------------------------------------------------


def _plan(ledger: Ledger, *, source: str = uid("t1")) -> str:
    ledger.tasks.submit(Task(id=source, intent="decompose"))
    ledger.artifacts.create(Artifact(id=uid("plan"), task_id=source, type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev1"), artifact_id=uid("plan")))
    return uid("rev1")


def test_open_initializes_child_ids_empty(ledger: Ledger) -> None:
    rev = _plan(ledger)
    opened = ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc1"),
            source_task_id=uid("t1"),
            accepted_plan_revision_id=rev,
            child_task_ids=["phantom"],  # caller-provided children must be ignored
        )
    )
    assert opened.child_task_ids == []


def test_add_child_rejected_after_complete(ledger: Ledger) -> None:
    rev = _plan(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(id=uid("dc1"), source_task_id=uid("t1"), accepted_plan_revision_id=rev)
    )
    ledger.decomposition_claims.complete(uid("dc1"))
    with pytest.raises(ValueError, match="not in_flight"):
        ledger.decomposition_claims.add_child(uid("dc1"), "child1")


def test_open_rejects_revision_from_another_task(ledger: Ledger) -> None:
    _plan(ledger, source=uid("t1"))  # rev1 belongs to t1's plan
    ledger.tasks.submit(Task(id=uid("t2"), intent="other"))
    with pytest.raises(ValueError, match="belongs to task"):
        ledger.decomposition_claims.open(
            DecompositionClaim(
                id=uid("dc1"), source_task_id=uid("t2"), accepted_plan_revision_id=uid("rev1")
            )
        )


# --- recovery_action (PR#12) ---------------------------------------------------------------------


def test_record_attempt_is_bounded(ledger: Ledger) -> None:
    from chorus.ledger import RecoveryAction, RecoveryKind

    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.recovery_actions.open(
        RecoveryAction(
            id=uid("rc1"), source_task_id=uid("t1"), kind=RecoveryKind.STRANDED, max_attempts=1
        )
    )
    ledger.recovery_actions.record_attempt(uid("rc1"))  # 0 -> 1 (cap)
    with pytest.raises(ValueError, match="exhausted"):
        ledger.recovery_actions.record_attempt(uid("rc1"))


# --- monitor (PR#13) -----------------------------------------------------------------------------


def _monitor_setup(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    _emp(ledger)


def test_fire_requires_pending(ledger: Ledger) -> None:
    _monitor_setup(ledger)
    ledger.monitors.arm(
        Monitor(id=uid("m1"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_now())
    )
    ledger.monitors.clear(uid("m1"))
    with pytest.raises(ValueError, match="not pending"):
        ledger.monitors.fire(uid("m1"))


def test_rearm_only_from_fired(ledger: Ledger) -> None:
    _monitor_setup(ledger)
    ledger.monitors.arm(
        Monitor(id=uid("m1"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_now())
    )
    with pytest.raises(ValueError, match="not fired"):
        ledger.monitors.rearm(uid("m1"), next_check_at=_now())


def test_db_rejects_pending_monitor_without_schedule(ledger: Ledger) -> None:
    _monitor_setup(ledger)
    with pytest.raises(LedgerIntegrityError):
        ledger._conn.execute(
            "INSERT INTO monitor (id, task_id, employee_id, next_check_at, status, max_attempts, "
            "attempt_count, recovery_policy, created_at) "
            "VALUES ('8ceaa873-be4e-5919-9e88-51a973e317e6', 'dc43bbe9-5688-5f9c-b00e-b3c6df2f5757', 'ae5cdfd6-100a-5cb7-8459-1a7390691451', NULL, 'pending', 1, 0, 'wake_owner', '2026-01-01')"
        )


# --- budget_incident / cost_event / budget_policy (PR#14) ----------------------------------------


def _policy(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    )


def _hard_incident(ledger: Ledger, iid: str = uid("bi1")) -> None:
    ledger.budget_incidents.open(
        BudgetIncident(
            id=iid,
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_now(),
        )
    )


def test_attach_approval_rejects_soft_incident(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.SOFT,
            amount_limit=80,
            amount_observed=85,
            window_start=_now(),
        )
    )
    with pytest.raises(ValueError, match="hard incidents"):
        ledger.budget_incidents.attach_approval(uid("bi1"), uid("ap1"))


def test_attach_and_resolve_on_unknown_incident_raise(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        ledger.budget_incidents.attach_approval(uid("ghost"), uid("ap1"))
    with pytest.raises(KeyError):
        ledger.budget_incidents.resolve(uid("ghost"))


def test_attach_approval_rejects_closed_incident(ledger: Ledger) -> None:
    _policy(ledger)
    _hard_incident(ledger)
    ledger.budget_incidents.dismiss(uid("bi1"))
    with pytest.raises(ValueError, match="not open"):
        ledger.budget_incidents.attach_approval(uid("bi1"), uid("ap1"))


def test_dismiss_only_affects_open(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.SOFT,
            amount_limit=80,
            amount_observed=85,
            window_start=_now(),
        )
    )
    ledger.budget_incidents.resolve(uid("bi1"))
    ledger.budget_incidents.dismiss(uid("bi1"))  # already resolved -> no-op
    got = ledger.budget_incidents.get(uid("bi1"))
    assert got is not None
    assert got.status.value == "resolved"


def test_hard_incident_resolve_needs_approved_approval(ledger: Ledger) -> None:
    _policy(ledger)
    _hard_incident(ledger)
    with pytest.raises(ValueError, match="approved approval"):
        ledger.budget_incidents.resolve(uid("bi1"))
    ledger.approvals.request(
        Approval(
            id=uid("ap1"),
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id=uid("bi1"),
            reason="cap",
        )
    )
    ledger.approvals.approve(uid("ap1"), decided_by_user_id=uid("u1"))
    ledger.budget_incidents.attach_approval(uid("bi1"), uid("ap1"))
    ledger.budget_incidents.resolve(uid("bi1"))  # now allowed
    got = ledger.budget_incidents.get(uid("bi1"))
    assert got is not None and got.status.value == "resolved"


def test_cost_event_rejects_negative_cost(ledger: Ledger) -> None:
    _emp(ledger)
    with pytest.raises(ValueError, match="non-negative"):
        ledger.cost_events.record(
            CostEvent(id=uid("ce1"), employee_id=uid("e1"), provider="p", model="m", cost_cents=-1)
        )


def test_db_rejects_negative_cost(ledger: Ledger) -> None:
    _emp(ledger)
    with pytest.raises(LedgerIntegrityError):
        ledger._conn.execute(
            "INSERT INTO cost_event (id, employee_id, provider, model, cost_cents, occurred_at) "
            "VALUES ('5a94c2b8-1bf5-574e-b719-a1f960848ced', 'ae5cdfd6-100a-5cb7-8459-1a7390691451', 'p', 'm', -5, '2026-01-01')"
        )


def test_policy_round_trips_timestamps(ledger: Ledger) -> None:
    _policy(ledger)
    got = ledger.budget_policies.get(uid("bp1"))
    assert got is not None
    assert got.created_at is not None
    assert got.updated_at is not None


# --- activity (PR#9) -----------------------------------------------------------------------------


def test_recent_rejects_nonpositive_limit(ledger: Ledger) -> None:
    with pytest.raises(ValueError, match="positive"):
        ledger.activity.recent(limit=0)
    with pytest.raises(ValueError, match="positive"):
        ledger.activity.recent(limit=-1)


# --- approval (PR#8) -----------------------------------------------------------------------------


def test_pending_excludes_expired(ledger: Ledger) -> None:
    past = _now() - timedelta(days=1)
    ledger.approvals.request(
        Approval(
            id=uid("ap_old"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t1"),
            reason="x",
            expires_at=past,
        )
    )
    ledger.approvals.request(
        Approval(
            id=uid("ap_live"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=uid("t2"),
            reason="y",
        )
    )
    assert [a.id for a in ledger.approvals.pending()] == [uid("ap_live")]


# --- message (PR#7) ------------------------------------------------------------------------------


def test_db_rejects_senderless_message(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("rep"), name=uid("rep"), role="engineer"))
    with pytest.raises(LedgerIntegrityError):
        ledger._conn.execute(
            "INSERT INTO message (id, to_employee_id, body, kind, created_at) "
            "VALUES ('8ceaa873-be4e-5919-9e88-51a973e317e6', '90099005-cc83-5c51-abe6-09fbb270f7ee', 'hi', 'instruction', '2026-01-01')"
        )


def test_send_with_one_sender_still_works(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="mgr", name="mgr", role="engineer"))
    ledger.employees.create(Employee(id=uid("rep"), name=uid("rep"), role="engineer"))
    sent = ledger.messages.send(
        Message(id=uid("m1"), from_employee_id="mgr", to_employee_id=uid("rep"), body="do X")
    )
    assert sent.from_employee_id == "mgr"
