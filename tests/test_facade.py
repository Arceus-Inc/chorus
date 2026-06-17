"""Facade heartbeat wiring (spec 10 §1) — tick / run_forever / stop delegate to the Scheduler.

The composition root owns the running kernel; these pin that ``Chorus.tick``/``run_forever``/``stop``
forward to the injected ``Scheduler`` (a fake here) rather than re-implementing the loop.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.errors import OrgInvariantViolation
from chorus.facade import Caps, Chorus
from chorus.heartbeat import TickReport
from chorus.ledger import Message, SqliteLedger, Task
from chorus.ledger._models import WakeReason
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee, GitWorkforce, LedgerWorkforce

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
        roles=RoleRegistry(),
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
        roles=RoleRegistry(),
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


# -- hire / terminate / register_role (spec 06 §3, spec 09 §1) ----------------


class _CancelSpyLedger:
    """A ledger stub that records the cancellation calls ``terminate`` must make."""

    def __init__(self) -> None:
        self.cancelled_runs: list[str] = []
        self.dropped_wakes: list[str] = []
        outer = self

        class _Runs:
            def cancel_running(self, *, employee_id: str) -> None:
                outer.cancelled_runs.append(employee_id)

        class _Wakes:
            def drop_queued(self, *, employee_id: str) -> None:
                outer.dropped_wakes.append(employee_id)

        self.runs = _Runs()
        self.wakes = _Wakes()


def _chorus_hr(org_repo: str, ledger: object, roles: RoleRegistry | None = None) -> Chorus:
    return Chorus(
        ledger=ledger,  # type: ignore[arg-type]
        workforce=GitWorkforce(org_repo),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=_FakeScheduler(),  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles=roles if roles is not None else RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def test_hire_validates_role_against_the_registry(tmp_path: Path) -> None:
    chorus = _chorus_hr(str(tmp_path / "org"), _CancelSpyLedger())
    emp = chorus.hire(name="Ada", role="engineer")
    assert emp.role == "engineer"
    with pytest.raises(OrgInvariantViolation):
        chorus.hire(name="Bad", role="nonexistent-role")


def test_terminate_cancels_in_flight_work(tmp_path: Path) -> None:
    ledger = _CancelSpyLedger()
    chorus = _chorus_hr(str(tmp_path / "org"), ledger)
    boss = chorus.hire(name="Boss", role="manager")
    rep = chorus.hire(name="Rep", role="engineer", reports_to=boss.id)
    chorus.terminate(rep.id)
    assert ledger.cancelled_runs == [rep.id]
    assert ledger.dropped_wakes == [rep.id]


def test_register_role_then_hire_into_it(tmp_path: Path) -> None:
    chorus = _chorus_hr(str(tmp_path / "org"), _CancelSpyLedger(), roles=RoleRegistry())
    with pytest.raises(OrgInvariantViolation):
        chorus.hire(name="Early", role="engineer")
    (plugin,) = (p for p in default_roles() if p.name == "engineer")
    chorus.register_role(plugin)
    assert chorus.hire(name="Ada", role="engineer").role == "engineer"


def _chorus_io(ledger: SqliteLedger) -> Chorus:
    """A facade over a real ledger whose live workforce is the ledger employee table."""
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=_FakeScheduler(),  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def test_export_then_import_workforce_round_trips_through_the_ledger(tmp_path: Path) -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus_io(ledger)
        chorus.hire(name="Boss", role="manager")
        chorus.hire(name="Alice", role="engineer", reports_to="boss")
        org = str(tmp_path / "org")
        assert chorus.export_workforce(org) == 2

        fresh = SqliteLedger.open(":memory:")
        try:
            assert _chorus_io(fresh).import_workforce(org) == 2
            alice = fresh.employees.get("alice")
            assert alice is not None and alice.reports_to == "boss"
        finally:
            fresh.close()
    finally:
        ledger.close()

