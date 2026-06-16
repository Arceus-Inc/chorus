"""Budgets wired into the tick (spec 04 §3 + spec 03 §3d).

Gate 1 blocks dispatch for an over-budget or paused employee before any beat starts; Gate 2 records
each beat's cost and, on a hard breach, pauses the scope — so the next tick won't dispatch it. With
no enforcer injected the tick behaves exactly as before (budgets off).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.budgets import BudgetEnforcer
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task
from chorus.ledger._models import BudgetPolicy, BudgetScope, CostEvent, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")
_COMPANY = "acme"


class _FakeBeat:
    """A stand-in beat runner that records its calls and reports a fixed cost."""

    def __init__(self, *, cost_cents: int = 0) -> None:
        self._cost_cents = cost_cents
        self.calls: list[str] = []

    async def run_task(self, *, task_id: str, intent: str, observer: object = None) -> BeatOutcome:
        self.calls.append(task_id)
        return BeatOutcome(passed=True, outcome={}, summary="done", cost_cents=self._cost_cents)


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _emp(ledger: SqliteLedger, employee_id: str) -> Employee:
    return ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))


def _employee_cap(ledger: SqliteLedger, employee_id: str, amount: int) -> None:
    ledger.budget_policies.create(
        BudgetPolicy(id="bp1", scope_type=BudgetScope.EMPLOYEE, scope_id=employee_id, amount=amount)
    )


def _spend(ledger: SqliteLedger, employee_id: str, cents: int) -> None:
    ledger.cost_events.record(
        CostEvent(id=f"seed_{cents}", employee_id=employee_id, provider="p", model="m",
                  cost_cents=cents, occurred_at=_NOW)
    )


def _assigned_wake(ledger: SqliteLedger, *, task_id: str, employee_id: str, wake_id: str) -> None:
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee_id)
    )
    ledger.wakes.enqueue(
        Wake(id=wake_id, employee_id=employee_id, reason=WakeReason.TASK_ASSIGNED,
             payload={"task_id": task_id})
    )


def _wired(
    ledger: SqliteLedger, beat: _FakeBeat, *employees: Employee, enforcer: BudgetEnforcer | None
) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(*employees),
        beat_runner=beat,
        max_concurrent_runs=1,
        budget_enforcer=enforcer,
    )


async def test_gate1_blocks_dispatch_for_an_over_budget_employee(ledger: SqliteLedger) -> None:
    e1 = _emp(ledger, "e1")
    _employee_cap(ledger, "e1", 100)
    _spend(ledger, "e1", 100)  # already at the cap
    beat = _FakeBeat()
    sched = _wired(ledger, beat, e1, enforcer=BudgetEnforcer(ledger, company_id=_COMPANY))
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == []  # never dispatched
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.TODO  # not checked out
    assert report.budget_gated == 1


async def test_gate1_allows_dispatch_under_budget(ledger: SqliteLedger) -> None:
    e1 = _emp(ledger, "e1")
    _employee_cap(ledger, "e1", 100)
    _spend(ledger, "e1", 50)
    beat = _FakeBeat()
    sched = _wired(ledger, beat, e1, enforcer=BudgetEnforcer(ledger, company_id=_COMPANY))
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]


async def test_gate2_beat_cost_trips_hard_stop_then_next_dispatch_is_gated(
    ledger: SqliteLedger,
) -> None:
    e1 = _emp(ledger, "e1")
    _employee_cap(ledger, "e1", 100)
    beat = _FakeBeat(cost_cents=150)  # one beat blows the cap
    enforcer = BudgetEnforcer(ledger, company_id=_COMPANY)
    sched = _wired(ledger, beat, e1, enforcer=enforcer)

    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")
    await sched.tick(_NOW)
    await sched.drain()
    assert beat.calls == ["t1"]  # the first beat ran
    assert enforcer.invocation_block("e1", now=_NOW) is not None  # its cost paused the scope

    _assigned_wake(ledger, task_id="t2", employee_id="e1", wake_id="w2")
    report = await sched.tick(_NOW)
    await sched.drain()
    assert beat.calls == ["t1"]  # t2 never dispatched — gated
    assert report.budget_gated == 1


async def test_no_enforcer_means_budgets_are_off(ledger: SqliteLedger) -> None:
    e1 = _emp(ledger, "e1")
    _employee_cap(ledger, "e1", 100)
    _spend(ledger, "e1", 500)  # wildly over — but no enforcer injected
    beat = _FakeBeat()
    sched = _wired(ledger, beat, e1, enforcer=None)
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]  # dispatched despite over-budget — gating is opt-in


async def test_cost_event_is_recorded_even_with_budgets_off(ledger: SqliteLedger) -> None:
    e1 = _emp(ledger, "e1")
    beat = _FakeBeat(cost_cents=42)
    sched = _wired(ledger, beat, e1, enforcer=None)
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]
    assert ledger.cost_events.spent_cents("e1") == 42  # the spend ledger fills regardless of gating
