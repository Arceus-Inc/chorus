"""Facade heartbeat wiring (spec 10 §1) — tick / run_forever / stop delegate to the Scheduler.

The composition root owns the running kernel; these pin that ``Chorus.tick``/``run_forever``/``stop``
forward to the injected ``Scheduler`` (a fake here) rather than re-implementing the loop.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.facade import Caps, Chorus
from chorus.heartbeat import TickReport
from chorus.ledger import Message, SqliteLedger, Task
from chorus.ledger._models import WakeReason
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_REPORT = TickReport(at=datetime(2026, 6, 16, tzinfo=UTC))


class _FakeScheduler:
    """Records the heartbeat calls the facade is meant to forward."""

    def __init__(self) -> None:
        self.tick_calls = 0
        self.ran = False
        self.stopped = False

    async def tick_once(self) -> TickReport:
        self.tick_calls += 1
        return _REPORT

    async def run(self) -> None:
        self.ran = True

    def stop(self) -> None:
        self.stopped = True


def _chorus(scheduler: _FakeScheduler) -> Chorus:
    # only the scheduler seam is exercised here; the rest can be inert
    return Chorus(
        ledger=None,  # type: ignore[arg-type]
        workforce=None,  # type: ignore[arg-type]
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=scheduler,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles={},
        caps=Caps(),
    )


async def test_tick_delegates_to_scheduler() -> None:
    sched = _FakeScheduler()
    report = await _chorus(sched).tick()
    assert report is _REPORT
    assert sched.tick_calls == 1


async def test_run_forever_delegates_to_scheduler() -> None:
    sched = _FakeScheduler()
    await _chorus(sched).run_forever()
    assert sched.ran is True


def test_stop_delegates_to_scheduler() -> None:
    sched = _FakeScheduler()
    chorus = _chorus(sched)
    chorus.stop()
    assert sched.stopped is True


def _chorus_on(ledger: SqliteLedger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=None,  # type: ignore[arg-type]
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=_FakeScheduler(),  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles={},
        caps=Caps(),
    )


def test_assign_wakes_through_the_facade() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
        ledger.tasks.submit(Task(id="t1", intent="ship"))
        wake = _chorus_on(ledger).assign("t1", "e1")
        assert wake is not None and wake.reason is WakeReason.TASK_ASSIGNED
        assert [w.id for w in ledger.wakes.queued(employee_id="e1")] == [wake.id]
    finally:
        ledger.close()


def test_send_message_wakes_through_the_facade() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="mgr", name="m", role="manager"))
        ledger.employees.create(Employee(id="rep", name="r", role="engineer"))
        wake = _chorus_on(ledger).send_message(
            Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="hi")
        )
        assert wake.reason is WakeReason.MESSAGE and wake.employee_id == "rep"
        assert [m.id for m in ledger.messages.inbox("rep")] == ["m1"]
    finally:
        ledger.close()
