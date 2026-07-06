"""The kernel run loop — ``Scheduler.run()`` drives ``tick()`` on a clock until stopped (spec 03 §3).

The loop is the one piece that turns the kernel from "tick is callable" into a running heartbeat.
These drive it deterministically: an injected clock + an injected ``sleep`` (no real time passes) let
a test run an exact number of pulses, prove the loop actually dispatches across ticks, and prove it
stops cleanly + drains in-flight beats.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task
from chorus.ledger._models import TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_START = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    """A stand-in :class:`BeatRunner` returning a canned pass and recording the tasks it ran."""

    def __init__(self) -> None:
        self.calls: list[str] = []

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
        self.calls.append(task_id)
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _stop_after(
    pulses: list[datetime], n: int, sched_box: list[Scheduler]
) -> tuple[Callable[[], datetime], Callable[[float], Awaitable[None]]]:
    """A fake clock + sleep: advance time each pulse, stop the scheduler after ``n`` pulses."""
    clock_at = [_START]

    def clock() -> datetime:
        return clock_at[0]

    async def sleep(seconds: float) -> None:
        clock_at[0] += timedelta(seconds=seconds)
        pulses.append(clock_at[0])
        if len(pulses) >= n:
            sched_box[0].stop()

    return clock, sleep


async def test_run_ticks_until_stopped(ledger: SqliteLedger) -> None:
    pulses: list[datetime] = []
    box: list[Scheduler] = []
    clock, sleep = _stop_after(pulses, 3, box)
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(),
        beat_runner=_FakeBeat(),
        clock=clock,
        sleep=sleep,
        tick_interval_s=1.0,
    )
    box.append(sched)

    await sched.run()

    assert len(pulses) == 3  # exactly three pulses, then the loop saw stop() and exited


async def test_run_dispatches_a_beat_across_ticks(ledger: SqliteLedger) -> None:
    e1 = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(
        Task(id="t1", intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="e1", reason=WakeReason.MANUAL, payload={"task_id": "t1"})
    )
    beat = _FakeBeat()
    pulses: list[datetime] = []
    box: list[Scheduler] = []
    clock, sleep = _stop_after(pulses, 1, box)
    sched = Scheduler(
        ledger=ledger, workforce=_FakeWorkforce(e1), beat_runner=beat, clock=clock, sleep=sleep
    )
    box.append(sched)

    await sched.run()  # one pulse dispatches the beat; the loop drains it on exit

    assert beat.calls == ["t1"]
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.DONE


async def test_stop_before_run_does_no_pulses(ledger: SqliteLedger) -> None:
    pulses: list[datetime] = []
    box: list[Scheduler] = []
    clock, sleep = _stop_after(pulses, 99, box)
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(),
        beat_runner=_FakeBeat(),
        clock=clock,
        sleep=sleep,
    )
    box.append(sched)
    sched.stop()  # stopped before it ever runs

    await sched.run()

    assert pulses == []  # the while-guard saw stop() up front; never ticked


async def test_tick_once_uses_the_injected_clock(ledger: SqliteLedger) -> None:
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(),
        beat_runner=_FakeBeat(),
        clock=lambda: _START,
    )
    report = await sched.tick_once()
    assert report.at == _START
