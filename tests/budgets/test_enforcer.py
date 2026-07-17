"""Two-gate budget enforcement (spec 04 §3) — Gate 1 block, Gate 2 incidents/kill, resolution + e2e.

Every component exercised against a real migrated ledger: the live-spend block, the soft/hard
incident raising, the hard-stop kill of in-flight work, and the human resume/dismiss resolutions,
plus a full lifecycle e2e (under → warn → breach → kill → resume).
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest

from chorus.budgets import BlockReason, BudgetEnforcer
from chorus.ledger import Ledger, Task
from chorus.ledger._models import (
    ApprovalStatus,
    ApprovalSubjectKind,
    BudgetIncidentStatus,
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
    CostEvent,
    Run,
    RunStatus,
    Wake,
    WakeReason,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)
COMPANY = "acme"
_ids = itertools.count()


def _enforcer(ledger: Ledger) -> BudgetEnforcer:
    return BudgetEnforcer(ledger, company_id=COMPANY)


def _emp(ledger: Ledger, employee_id: str) -> None:
    ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))


def _policy(
    ledger: Ledger,
    *,
    scope: BudgetScope,
    scope_id: str,
    amount: int,
    warn_percent: int = 80,
    hard_stop: bool = True,
    policy_id: str = uid("bp1"),
    metric: str = "cost_cents",
    window_kind: str = "monthly",
) -> str:
    ledger.budget_policies.create(
        BudgetPolicy(
            id=policy_id,
            scope_type=scope,
            scope_id=scope_id,
            amount=amount,
            warn_percent=warn_percent,
            hard_stop_enabled=hard_stop,
            metric=metric,
            window_kind=window_kind,
        )
    )
    return policy_id


def _spend(ledger: Ledger, employee_id: str, cents: int) -> CostEvent:
    event = CostEvent(
        id=uid(f"ce_{next(_ids)}"),
        employee_id=employee_id,
        provider="azure",
        model="gpt-5.2",
        cost_cents=cents,
        occurred_at=NOW,
    )
    return ledger.cost_events.record(event)


def _inflight(ledger: Ledger, employee_id: str) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(
        Run(id=uid("r1"), employee_id=employee_id, task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.wakes.enqueue(Wake(id=uid("w1"), employee_id=employee_id, reason=WakeReason.MANUAL))


# -- Gate 1: invocation block ---------------------------------------------------------------------


def test_gate1_allows_when_no_policy(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is None


def test_gate1_allows_under_budget(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    _spend(ledger, uid("e1"), 50)
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is None


def test_gate1_blocks_employee_over_budget(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    _spend(ledger, uid("e1"), 100)
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_OVER


def test_gate1_company_reason_outranks_employee(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.COMPANY, scope_id=COMPANY, amount=100, policy_id=uid("bpc"))
    _policy(
        ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, policy_id=uid("bpe")
    )
    _spend(ledger, uid("e1"), 150)  # over both
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is BlockReason.COMPANY_OVER


def test_gate1_paused_persists_even_when_under_budget(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)  # hard breach -> paused
    ledger.budget_policies.set_amount(uid("bp1"), 1000)  # now under budget, but incident stays open
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_PAUSED


def test_gate1_ignores_over_when_hard_stop_disabled(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, hard_stop=False)
    _spend(ledger, uid("e1"), 200)
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is None  # soft-only never blocks


def test_gate1_paused_policy_is_not_masked_by_an_over_policy_in_same_scope(
    ledger: Ledger,
) -> None:
    # Two cost policies for one employee (distinct windows — the unique key is scope/metric/window).
    # bp2 (monthly) gets paused; bp1 (weekly) ends up merely over and sorts first by id, so a
    # first-match loop would report EMPLOYEE_OVER and mask the pause — paused must still win.
    _emp(ledger, uid("e1"))
    _policy(
        ledger,
        scope=BudgetScope.EMPLOYEE,
        scope_id=uid("e1"),
        amount=50,
        policy_id=uid("bp2"),
        window_kind="monthly",
    )
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 60), now=NOW)  # bp2 hard breach -> paused
    _policy(
        ledger,
        scope=BudgetScope.EMPLOYEE,
        scope_id=uid("e1"),
        amount=100,
        policy_id=uid("bp1"),
        window_kind="weekly",
    )
    _spend(
        ledger, uid("e1"), 60
    )  # total 120 -> bp1 (weekly) is over (recorded only, not evaluated)
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_PAUSED


def test_gate1_ignores_a_non_cost_metric_policy(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    # a tokens cap of 1 — cost-cents spend must not be evaluated against it
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=1, metric="tokens")
    _spend(ledger, uid("e1"), 100)  # 100 cents — would blow a 1-cent cost cap, but this caps tokens
    assert _enforcer(ledger).invocation_block(uid("e1"), now=NOW) is None


def test_gate2_does_not_raise_for_a_non_cost_metric_policy(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=1, metric="tokens")
    assert _enforcer(ledger).on_cost_event(_spend(ledger, uid("e1"), 100), now=NOW) == []


# -- Gate 2: on cost event ------------------------------------------------------------------------


def test_gate2_no_incident_under_warn(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, warn_percent=80)
    assert _enforcer(ledger).on_cost_event(_spend(ledger, uid("e1"), 50), now=NOW) == []


def test_gate2_raises_soft_at_warn_without_blocking(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, warn_percent=80)
    enf = _enforcer(ledger)
    [incident] = enf.on_cost_event(_spend(ledger, uid("e1"), 80), now=NOW)
    assert incident.threshold_type is BudgetThreshold.SOFT
    assert incident.approval_id is None
    assert enf.invocation_block(uid("e1"), now=NOW) is None  # a soft incident does not pause


def test_gate2_soft_is_idempotent_within_a_window(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, warn_percent=80)
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 80), now=NOW)
    assert (
        enf.on_cost_event(_spend(ledger, uid("e1"), 5), now=NOW) == []
    )  # already warned this window


def test_gate2_hard_breach_pairs_approval_and_kills_inflight(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    _inflight(ledger, uid("e1"))
    [incident] = _enforcer(ledger).on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)

    assert incident.threshold_type is BudgetThreshold.HARD
    assert incident.amount_observed == 120
    assert incident.approval_id is not None
    approval = ledger.approvals.get(incident.approval_id)
    assert approval is not None
    assert approval.subject_kind is ApprovalSubjectKind.BUDGET_INCIDENT
    assert approval.subject_id == incident.id
    # in-flight work killed
    run = ledger.runs.get(uid("r1"))
    assert run is not None and run.status is RunStatus.CANCELLED
    assert ledger.wakes.queued(employee_id=uid("e1")) == []


def test_gate2_hard_is_idempotent(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)
    assert enf.on_cost_event(_spend(ledger, uid("e1"), 30), now=NOW) == []  # already paused


def test_gate2_company_breach_kills_whole_workforce(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _emp(ledger, uid("e2"))
    _policy(ledger, scope=BudgetScope.COMPANY, scope_id=COMPANY, amount=100)
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(
        Run(id=uid("r2"), employee_id=uid("e2"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.wakes.enqueue(Wake(id=uid("w2"), employee_id=uid("e2"), reason=WakeReason.MANUAL))
    _enforcer(ledger).on_cost_event(
        _spend(ledger, uid("e1"), 120), now=NOW
    )  # e1 spend trips company
    run = ledger.runs.get(uid("r2"))
    assert run is not None and run.status is RunStatus.CANCELLED  # e2 killed too
    assert ledger.wakes.queued() == []


# -- resolution -----------------------------------------------------------------------------------


def test_resume_raises_cap_and_clears_the_pause(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    enf = _enforcer(ledger)
    [incident] = enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)

    enf.raise_budget_and_resume(uid("bp1"), 500, now=NOW, decided_by_user_id=uid("u1"))

    assert enf.invocation_block(uid("e1"), now=NOW) is None  # neither paused nor over (500 > 120)
    resolved = ledger.budget_incidents.get(incident.id)
    assert resolved is not None and resolved.status is BudgetIncidentStatus.RESOLVED


def test_resume_rejects_a_cap_below_observed(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)
    with pytest.raises(ValueError, match="must exceed observed"):
        enf.raise_budget_and_resume(uid("bp1"), 110, now=NOW, decided_by_user_id=uid("u1"))


def test_dismiss_denies_approval_and_keeps_scope_paused(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    enf = _enforcer(ledger)
    [incident] = enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)

    enf.dismiss(incident.id, decided_by_user_id=uid("u1"))

    assert incident.approval_id is not None
    approval = ledger.approvals.get(incident.approval_id)
    assert approval is not None and approval.status is ApprovalStatus.DENIED
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_PAUSED  # still paused


# -- end to end -----------------------------------------------------------------------------------


def test_e2e_budget_lifecycle(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100, warn_percent=80)
    enf = _enforcer(ledger)

    # 1. under budget — no incident, beat allowed
    assert enf.on_cost_event(_spend(ledger, uid("e1"), 50), now=NOW) == []
    assert enf.invocation_block(uid("e1"), now=NOW) is None

    # 2. cross the warn line — a soft incident, still allowed
    [soft] = enf.on_cost_event(_spend(ledger, uid("e1"), 35), now=NOW)  # total 85
    assert soft.threshold_type is BudgetThreshold.SOFT
    assert enf.invocation_block(uid("e1"), now=NOW) is None

    # 3. breach the cap with work in flight — hard incident, paused + killed
    _inflight(ledger, uid("e1"))
    [hard] = enf.on_cost_event(_spend(ledger, uid("e1"), 30), now=NOW)  # total 115
    assert hard.threshold_type is BudgetThreshold.HARD
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_PAUSED
    run = ledger.runs.get(uid("r1"))
    assert run is not None and run.status is RunStatus.CANCELLED
    assert ledger.wakes.queued(employee_id=uid("e1")) == []

    # 4. a human raises the cap and resumes
    enf.raise_budget_and_resume(uid("bp1"), 500, now=NOW, decided_by_user_id="ceo")
    assert enf.invocation_block(uid("e1"), now=NOW) is None


# -- edge cases ----------------------------------------------------------------------------------


def test_gate1_company_paused(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.COMPANY, scope_id=COMPANY, amount=100)
    enf = _enforcer(ledger)
    enf.on_cost_event(_spend(ledger, uid("e1"), 120), now=NOW)  # company hard incident
    ledger.budget_policies.set_amount(
        uid("bp1"), 1000
    )  # under budget, but the company incident persists
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.COMPANY_PAUSED


def test_resume_with_no_open_incident_just_raises_the_cap(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    _policy(ledger, scope=BudgetScope.EMPLOYEE, scope_id=uid("e1"), amount=100)
    _spend(ledger, uid("e1"), 120)  # over, but Gate 2 never ran — no incident to resolve
    enf = _enforcer(ledger)
    assert enf.invocation_block(uid("e1"), now=NOW) is BlockReason.EMPLOYEE_OVER
    enf.raise_budget_and_resume(uid("bp1"), 500, now=NOW, decided_by_user_id=uid("u1"))
    assert enf.invocation_block(uid("e1"), now=NOW) is None


def test_resume_unknown_policy_raises(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        _enforcer(ledger).raise_budget_and_resume(
            uid("ghost"), 100, now=NOW, decided_by_user_id=uid("u1")
        )


def test_dismiss_unknown_incident_raises(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        _enforcer(ledger).dismiss(uid("ghost"), decided_by_user_id=uid("u1"))
