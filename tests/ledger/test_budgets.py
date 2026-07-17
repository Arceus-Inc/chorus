"""Budget repos — two-gate money (spec 01 Cluster E, spec 04).

``budget_policy`` is the limit (one per scope/metric/window). ``budget_incident`` is a breach record
(one open per policy/window/threshold) that a hard stop attaches an ``approval`` to. ``cost_event`` is
the immutable spend ledger — ``spent`` is **recomputed live from cost_events, never trusted** as a
stored counter (Paperclip rule).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    Approval,
    ApprovalSubjectKind,
    BudgetIncident,
    BudgetIncidentStatus,
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
    CostEvent,
    Ledger,
    LedgerIntegrityError,
    Run,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _at(seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def _employee(ledger: Ledger, eid: str = uid("e1")) -> str:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    return eid


# --- budget_policy -------------------------------------------------------------------------------


def test_policy_create_and_find(ledger: Ledger) -> None:
    _employee(ledger)
    created = ledger.budget_policies.create(
        BudgetPolicy(
            id=uid("bp1"),
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=uid("e1"),
            amount=10_000,
            warn_percent=75,
        )
    )
    assert created.hard_stop_enabled is True
    found = ledger.budget_policies.find(
        scope_type=BudgetScope.EMPLOYEE,
        scope_id=uid("e1"),
        metric="cost_cents",
        window_kind="monthly",
    )
    assert found is not None
    assert found.id == uid("bp1")
    assert found.amount == 10_000
    assert found.warn_percent == 75


def test_policy_scope_is_exact_once(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=1)
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.budget_policies.create(
            BudgetPolicy(
                id=uid("bp2"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=2
            )
        )


def test_policy_by_scope_lists(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.budget_policies.create(
        BudgetPolicy(
            id=uid("bp1"),
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=uid("e1"),
            amount=1,
            metric="cost_cents",
        )
    )
    ledger.budget_policies.create(
        BudgetPolicy(
            id=uid("bp2"),
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=uid("e1"),
            amount=2,
            metric="tokens",
        )
    )
    got = ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, uid("e1"))
    assert {p.id for p in got} == {uid("bp1"), uid("bp2")}


# --- budget_incident -----------------------------------------------------------------------------


def _policy(ledger: Ledger) -> str:
    _employee(ledger)
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bp1"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    )
    return uid("bp1")


def test_incident_open_and_get(ledger: Ledger) -> None:
    _policy(ledger)
    opened = ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_at(0),
        )
    )
    got = ledger.budget_incidents.get(opened.id)
    assert got is not None
    assert got.status is BudgetIncidentStatus.OPEN
    assert got.threshold_type is BudgetThreshold.HARD
    assert got.amount_observed == 120
    assert got.approval_id is None


def test_incident_window_is_exact_once(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_at(0),
        )
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.budget_incidents.open(
            BudgetIncident(
                id=uid("bi2"),
                policy_id=uid("bp1"),
                threshold_type=BudgetThreshold.HARD,
                amount_limit=100,
                amount_observed=130,
                window_start=_at(0),
            )
        )


def test_dismiss_frees_the_window(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_at(0),
        )
    )
    ledger.budget_incidents.dismiss(uid("bi1"))
    # window freed: a fresh incident for the same window/threshold is allowed
    again = ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi2"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=140,
            window_start=_at(0),
        )
    )
    assert again.status is BudgetIncidentStatus.OPEN


def test_attach_approval_gates_hard_stop(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.approvals.request(
        Approval(
            id=uid("ap1"),
            subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
            subject_id=uid("bi1"),
            reason="hard cap",
        )
    )
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_at(0),
        )
    )
    ledger.budget_incidents.attach_approval(uid("bi1"), uid("ap1"))
    got = ledger.budget_incidents.get(uid("bi1"))
    assert got is not None
    assert got.approval_id == uid("ap1")


def test_open_for_policy_lists_open_only(ledger: Ledger) -> None:
    _policy(ledger)
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi1"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.SOFT,
            amount_limit=80,
            amount_observed=85,
            window_start=_at(0),
        )
    )
    ledger.budget_incidents.open(
        BudgetIncident(
            id=uid("bi2"),
            policy_id=uid("bp1"),
            threshold_type=BudgetThreshold.HARD,
            amount_limit=100,
            amount_observed=120,
            window_start=_at(0),
        )
    )
    ledger.budget_incidents.resolve(uid("bi1"))
    assert [i.id for i in ledger.budget_incidents.open_for_policy(uid("bp1"))] == [uid("bi2")]


# --- cost_event ----------------------------------------------------------------------------------


def test_cost_event_record_and_spent(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(Run(id=uid("run1"), employee_id=uid("e1"), task_id=uid("t1")))
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce1"),
            employee_id=uid("e1"),
            task_id=uid("t1"),
            run_id=uid("run1"),
            provider="anthropic",
            model="claude",
            cost_cents=300,
            input_tokens=100,
            output_tokens=50,
            occurred_at=_at(10),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce2"),
            employee_id=uid("e1"),
            provider="anthropic",
            model="claude",
            cost_cents=200,
            occurred_at=_at(20),
        )
    )
    assert ledger.cost_events.spent_cents(uid("e1")) == 500


def test_budget_policies_all_lists_every_policy(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.budget_policies.create(
        BudgetPolicy(
            id=uid("bpc"), scope_type=BudgetScope.COMPANY, scope_id=uid("acme"), amount=1000
        )
    )
    ledger.budget_policies.create(
        BudgetPolicy(id=uid("bpe"), scope_type=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    )
    ids = {p.id for p in ledger.budget_policies.all()}
    assert ids == {uid("bpc"), uid("bpe")}


def test_for_run_returns_a_runs_cost_events_with_usage(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(Run(id=uid("run1"), employee_id=uid("e1"), task_id=uid("t1")))
    ledger.runs.create(Run(id=uid("run2"), employee_id=uid("e1"), task_id=uid("t1")))
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce1"),
            employee_id=uid("e1"),
            task_id=uid("t1"),
            run_id=uid("run1"),
            provider="dream",
            model="gpt-5.2",
            cost_cents=300,
            input_tokens=1200,
            output_tokens=340,
            occurred_at=_at(10),
        )
    )
    ledger.cost_events.record(  # a different run — must not be returned
        CostEvent(
            id=uid("ce2"),
            employee_id=uid("e1"),
            run_id=uid("run2"),
            provider="dream",
            model="m",
            cost_cents=10,
            occurred_at=_at(20),
        )
    )
    events = ledger.cost_events.for_run(uid("run1"))
    assert [e.id for e in events] == [uid("ce1")]
    assert events[0].model == "gpt-5.2"
    assert events[0].input_tokens == 1200
    assert events[0].output_tokens == 340


def test_spent_cents_respects_window(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce1"),
            employee_id=uid("e1"),
            provider="p",
            model="m",
            cost_cents=100,
            occurred_at=_at(10),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce2"),
            employee_id=uid("e1"),
            provider="p",
            model="m",
            cost_cents=400,
            occurred_at=_at(100),
        )
    )
    assert ledger.cost_events.spent_cents(uid("e1"), since=_at(50)) == 400


def test_spent_cents_is_per_employee(ledger: Ledger) -> None:
    _employee(ledger, uid("e1"))
    _employee(ledger, uid("e2"))
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce1"),
            employee_id=uid("e1"),
            provider="p",
            model="m",
            cost_cents=100,
            occurred_at=_at(10),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce2"),
            employee_id=uid("e2"),
            provider="p",
            model="m",
            cost_cents=999,
            occurred_at=_at(10),
        )
    )
    assert ledger.cost_events.spent_cents(uid("e1")) == 100


def test_total_spent_cents_sums_the_whole_workforce(ledger: Ledger) -> None:
    _employee(ledger, uid("e1"))
    _employee(ledger, uid("e2"))
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce1"),
            employee_id=uid("e1"),
            provider="p",
            model="m",
            cost_cents=100,
            occurred_at=_at(10),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("ce2"),
            employee_id=uid("e2"),
            provider="p",
            model="m",
            cost_cents=250,
            occurred_at=_at(100),
        )
    )
    assert ledger.cost_events.total_spent_cents() == 350  # lifetime (no window)
    assert ledger.cost_events.total_spent_cents(since=_at(50)) == 250  # windowed
