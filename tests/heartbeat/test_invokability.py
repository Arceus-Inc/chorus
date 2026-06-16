"""The invokability gate wired into the tick (spec 06 §3).

Gate 0 runs before the budget gate and the dispatch CAS: a terminated or orphaned employee has its
wake *cancelled* (wake done, task ``cancelled``); a paused employee has its wake *released* (it
waits for a resume). A healthy employee — including one with a healthy manager chain — dispatches
exactly as before, so the gate is backward-compatible.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task
from chorus.ledger._models import TaskStatus
from chorus.workforce import Employee, EmployeeStatus

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    """A stand-in beat runner that records the task ids it was asked to run."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None
    ) -> BeatOutcome:
        self.calls.append(task_id)
        return BeatOutcome(passed=True, outcome={}, summary="done", cost_cents=0)


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]  # KeyError on unknown — the orphan case


def _employee(
    employee_id: str,
    *,
    status: EmployeeStatus = EmployeeStatus.IDLE,
    reports_to: str | None = None,
) -> Employee:
    return Employee(
        id=employee_id, name=employee_id, role="engineer", reports_to=reports_to, status=status
    )


def _assigned_wake(ledger: SqliteLedger, *, task_id: str, employee_id: str, wake_id: str) -> None:
    # The task/wake FK the employees table, so seed a ledger row independent of the fake workforce
    # (the workforce is the status source; the ledger row only satisfies referential integrity).
    if ledger.employees.get(employee_id) is None:
        ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee_id)
    )
    ledger.wakes.enqueue(
        Wake(
            id=wake_id,
            employee_id=employee_id,
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )


def _wired(ledger: SqliteLedger, beat: _FakeBeat, *employees: Employee) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(*employees),
        beat_runner=beat,
        max_concurrent_runs=4,
    )


async def test_terminated_employee_cancels_the_wake_and_task(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    sched = _wired(ledger, beat, _employee("e1", status=EmployeeStatus.TERMINATED))
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == []
    assert ledger.wakes.queued(employee_id="e1") == []
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.CANCELLED
    assert report.invokability_cancelled == 1
    assert report.invokability_skipped == 0


async def test_paused_employee_holds_the_wake(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    sched = _wired(ledger, beat, _employee("e1", status=EmployeeStatus.PAUSED))
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == []
    assert [w.id for w in ledger.wakes.queued(employee_id="e1")] == ["w1"]  # still waiting
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.TODO
    assert report.invokability_skipped == 1
    assert report.invokability_cancelled == 0


async def test_unknown_employee_cancels_the_wake(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    sched = _wired(ledger, beat)  # workforce knows nobody
    _assigned_wake(ledger, task_id="t1", employee_id="ghost", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == []
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.CANCELLED
    assert report.invokability_cancelled == 1


async def test_terminated_manager_orphans_the_report(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    boss = _employee("boss", status=EmployeeStatus.TERMINATED)
    rep = _employee("rep", reports_to="boss")
    sched = _wired(ledger, beat, boss, rep)
    _assigned_wake(ledger, task_id="t1", employee_id="rep", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == []
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.CANCELLED
    assert report.invokability_cancelled == 1


async def test_healthy_employee_dispatches(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    sched = _wired(ledger, beat, _employee("e1"))
    _assigned_wake(ledger, task_id="t1", employee_id="e1", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]
    assert report.invokability_cancelled == 0
    assert report.invokability_skipped == 0
    assert report.wakes_dispatched == 1


async def test_healthy_report_under_a_live_manager_dispatches(ledger: SqliteLedger) -> None:
    beat = _FakeBeat()
    boss = _employee("boss")
    rep = _employee("rep", reports_to="boss")
    sched = _wired(ledger, beat, boss, rep)
    _assigned_wake(ledger, task_id="t1", employee_id="rep", wake_id="w1")

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]
    assert report.wakes_dispatched == 1
    assert report.invokability_cancelled == 0
