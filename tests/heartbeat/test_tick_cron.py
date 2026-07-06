"""The tick's CRON + MONITOR steps wired end-to-end (spec 03 §3b, §3c).

A tick fires due routines (each writing a task + ``cron_due`` wake the same pass then dispatches),
and drains due monitors into ``monitor_due`` wakes — escalating to a recovery action when a monitor
exhausts its attempts. These exercise the wiring; the firing/monitor mechanics are unit-tested in
the cron and ledger suites.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger
from chorus.ledger._models import (
    Monitor,
    MonitorRecoveryPolicy,
    MonitorStatus,
    Routine,
    RoutineTrigger,
    Task,
    TaskStatus,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="done")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _wired(ledger: SqliteLedger, *employees: Employee, max_concurrent_runs: int = 4) -> Scheduler:
    return Scheduler(
        max_concurrent_runs=max_concurrent_runs,
        ledger=ledger,
        workforce=_FakeWorkforce(*employees),
        beat_runner=_FakeBeat(),
    )


def _routine(ledger: SqliteLedger, *, eid: str = "e1") -> None:
    ledger.routines.create(Routine(id="r1", employee_id=eid, intent_template="hourly sweep"))
    ledger.routine_triggers.create(
        RoutineTrigger(id="trig_r1", routine_id="r1", cron_expression="0 * * * *", next_run_at=_NOW)
    )


async def test_tick_fires_a_due_routine(ledger: SqliteLedger) -> None:
    e1 = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    _routine(ledger)
    sched = _wired(ledger, e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.routines_fired == 1
    (run,) = ledger.routine_runs.by_routine("r1")
    assert run.linked_task_id is not None
    spawned = ledger.tasks.get(run.linked_task_id)
    assert spawned is not None
    # The spawned task's cron_due wake was claimed + run in the same tick → done, one run.
    assert spawned.status is TaskStatus.DONE
    assert len(ledger.runs.for_task(run.linked_task_id)) == 1


async def test_tick_does_not_refire_an_advanced_edge(ledger: SqliteLedger) -> None:
    e1 = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    _routine(ledger)
    sched = _wired(ledger, e1)

    await sched.tick(_NOW)
    await sched.drain()
    # Immediately re-tick at the same instant: the edge already advanced an hour out, not due.
    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.routines_fired == 0
    assert len(ledger.routine_runs.by_routine("r1")) == 1


async def test_tick_drains_a_due_monitor_into_a_wake(ledger: SqliteLedger) -> None:
    e1 = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="wait on CI", assignee_employee_id="e1"))
    ledger.monitors.arm(
        Monitor(
            id="m1",
            task_id="t1",
            employee_id="e1",
            next_check_at=_NOW,
            max_attempts=2,  # first fire → FIRED, not exhausted
        )
    )
    sched = _wired(ledger, e1, max_concurrent_runs=0)  # isolate the monitor step from dispatch

    await sched.tick(_NOW)
    await sched.drain()

    fired = ledger.monitors.get("m1")
    assert fired is not None and fired.status is MonitorStatus.FIRED
    monitor_wakes = _monitor_due_wakes(ledger)
    assert len(monitor_wakes) == 1
    assert monitor_wakes[0].payload["task_id"] == "t1"


async def test_tick_escalates_an_exhausted_monitor_to_a_recovery(ledger: SqliteLedger) -> None:
    e1 = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="wait on CI", assignee_employee_id="e1"))
    ledger.monitors.arm(
        Monitor(
            id="m1",
            task_id="t1",
            employee_id="e1",
            next_check_at=_NOW,
            max_attempts=1,  # first fire → EXHAUSTED
            recovery_policy=MonitorRecoveryPolicy.ESCALATE,
        )
    )
    sched = _wired(ledger, e1, max_concurrent_runs=0)

    await sched.tick(_NOW)
    await sched.drain()

    exhausted = ledger.monitors.get("m1")
    assert exhausted is not None and exhausted.status is MonitorStatus.EXHAUSTED
    action = ledger.recovery_actions.active_for_source("t1")
    assert action is not None
    assert action.cause == "monitor_exhausted"
    assert _monitor_due_wakes(ledger) == []  # exhausted escalates instead of waking
    # the escalation is audited (spec 08 §5)
    assert any(a.verb.value == "recovered" for a in ledger.activity.by_subject("task", "t1"))


def _monitor_due_wakes(ledger: SqliteLedger) -> list[Wake]:
    return [w for w in ledger.wakes.queued() if w.reason is WakeReason.MONITOR_DUE]
