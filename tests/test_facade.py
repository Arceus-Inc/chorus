"""Facade heartbeat wiring (spec 10 §1) — tick / run_forever / stop delegate to the Scheduler.

The composition root owns the running kernel; these pin that ``Chorus.tick``/``run_forever``/``stop``
forward to the injected ``Scheduler`` (a fake here) rather than re-implementing the loop.
"""

from __future__ import annotations

from collections import UserDict
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.errors import OrgInvariantViolation
from chorus.facade import Caps, Chorus
from chorus.heartbeat import TickReport
from chorus.ledger import (
    AgentSession,
    AgentSessionStatus,
    Ledger,
    Message,
    RecoveryAction,
    RecoveryKind,
    RecoveryStatus,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.ledger._models import Wake, WakeReason, WakeStatus
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger, uid
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


async def test_stop_delegates_to_scheduler() -> None:
    sched = _FakeScheduler()
    chorus = _chorus(sched)
    await chorus.stop()
    assert sched.stopped is True  # a stop with no managed heartbeat just signals the loop


async def test_start_launches_a_background_heartbeat_and_stop_awaits_it() -> None:
    sched = _FakeScheduler()
    chorus = _chorus(sched)
    chorus.start()  # returns immediately — the heartbeat runs in the background
    await chorus.stop()  # signals + awaits the managed task so its beats drain
    assert sched.ran is True
    assert sched.stopped is True


async def test_start_is_idempotent_while_the_heartbeat_is_live() -> None:
    sched = _FakeScheduler()
    chorus = _chorus(sched)
    chorus.start()
    first = chorus._heartbeat
    chorus.start()  # a second start while live is a no-op — same task, not a second loop
    assert chorus._heartbeat is first
    await chorus.stop()


def _chorus_on(ledger: Ledger) -> Chorus:
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
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
        ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))
        wake = _chorus_on(ledger).assign(uid("t1"), uid("e1"))
        assert wake is not None and wake.reason is WakeReason.TASK_ASSIGNED
        assert [w.id for w in ledger.wakes.queued(employee_id=uid("e1"))] == [wake.id]
    finally:
        ledger.close()


def test_send_message_wakes_through_the_facade() -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="mgr", name="m", role="engineer"))
        ledger.employees.create(Employee(id=uid("rep"), name="r", role="engineer"))
        wake = _chorus_on(ledger).send_message(
            Message(id=uid("m1"), from_employee_id="mgr", to_employee_id=uid("rep"), body="hi")
        )
        assert wake.reason is WakeReason.MESSAGE and wake.employee_id == uid("rep")
        assert [m.id for m in ledger.messages.inbox(uid("rep"))] == [uid("m1")]
    finally:
        ledger.close()


def test_cancel_task_terminalizes_only_its_live_work_and_is_idempotent() -> None:
    ledger = open_test_ledger()
    try:
        employee_id, task_id = uid("e1"), uid("t1")
        ledger.employees.create(Employee(id=employee_id, name="a", role="engineer"))
        ledger.tasks.submit(Task(id=task_id, intent="stop", assignee_employee_id=employee_id))
        ledger.tasks.set_status(task_id, TaskStatus.TODO)
        claimed = ledger.wakes.enqueue(
            Wake(
                id=uid("claimed"),
                employee_id=employee_id,
                reason=WakeReason.TASK_ASSIGNED,
                payload=UserDict(task_id=task_id),
            )
        )
        assert [wake.id for wake in ledger.wakes.claim(limit=1)] == [claimed.id]
        queued = ledger.wakes.enqueue(
            Wake(
                id=uid("queued"),
                employee_id=employee_id,
                reason=WakeReason.MESSAGE,
                payload=UserDict(task_id=task_id),
            )
        )
        other_task_id = uid("t2")
        ledger.tasks.submit(Task(id=other_task_id, intent="keep", assignee_employee_id=employee_id))
        other_wake = ledger.wakes.enqueue(
            Wake(
                id=uid("other"),
                employee_id=employee_id,
                reason=WakeReason.TASK_ASSIGNED,
                payload=UserDict(task_id=other_task_id),
            )
        )
        run_id = uid("r1")
        assert ledger.tasks.checkout(task_id, employee_id=employee_id, run_id=run_id)
        ledger.runs.create(
            Run(id=run_id, employee_id=employee_id, task_id=task_id, status=RunStatus.RUNNING)
        )
        session = ledger.agent_sessions.open(
            AgentSession(
                id=uid("s1"),
                dream_session_key=uid("dream"),
                employee_id=employee_id,
                task_id=task_id,
            )
        )
        action = ledger.recovery_actions.open(
            RecoveryAction(
                id=uid("recovery"), source_task_id=task_id, kind=RecoveryKind.STRANDED
            )
        )

        chorus = _chorus_on(ledger)
        assert chorus.cancel_task(task_id) is True
        assert chorus.cancel_task(task_id) is True

        task = ledger.tasks.get(task_id)
        assert task is not None
        assert task.status is TaskStatus.CANCELLED
        assert task.cancelled_at is not None
        assert task.checkout_run_id is None
        assert task.execution_run_id is None
        cancelled_run = ledger.runs.get(run_id)
        cancelled_session = ledger.agent_sessions.get(session.id)
        folded_recovery = ledger.recovery_actions.get(action.id)
        finished_claimed_wake = ledger.wakes.get(claimed.id)
        finished_queued_wake = ledger.wakes.get(queued.id)
        other_wake_after_cancel = ledger.wakes.get(other_wake.id)
        assert cancelled_run is not None
        assert cancelled_session is not None
        assert folded_recovery is not None
        assert finished_claimed_wake is not None
        assert finished_queued_wake is not None
        assert other_wake_after_cancel is not None
        assert cancelled_run.status is RunStatus.CANCELLED
        assert cancelled_session.status is AgentSessionStatus.ABORTED
        assert folded_recovery.status is RecoveryStatus.FOLDED
        assert finished_claimed_wake.status is WakeStatus.DONE
        assert finished_queued_wake.status is WakeStatus.DONE
        assert other_wake_after_cancel.status is WakeStatus.QUEUED

        ledger.runs.finish(run_id, RunStatus.SUCCEEDED)
        ledger.tasks.set_status(task_id, TaskStatus.DONE)
        run_after_late_finish = ledger.runs.get(run_id)
        task_after_late_finish = ledger.tasks.get(task_id)
        assert run_after_late_finish is not None
        assert task_after_late_finish is not None
        assert run_after_late_finish.status is RunStatus.CANCELLED
        assert task_after_late_finish.status is TaskStatus.CANCELLED
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
    emp = chorus.hire(name="Ada", role="frontend_engineer")
    assert emp.role == "frontend_engineer"
    with pytest.raises(OrgInvariantViolation):
        chorus.hire(name="Bad", role="nonexistent-role")


def test_terminate_cancels_in_flight_work(tmp_path: Path) -> None:
    ledger = _CancelSpyLedger()
    chorus = _chorus_hr(str(tmp_path / "org"), ledger)
    boss = chorus.hire(name="Boss", role="frontend_engineer")
    rep = chorus.hire(name="Rep", role="frontend_engineer", reports_to=boss.id)
    chorus.terminate(rep.id)
    assert ledger.cancelled_runs == [rep.id]
    assert ledger.dropped_wakes == [rep.id]


def test_register_role_then_hire_into_it(tmp_path: Path) -> None:
    from chorus_employee.engineer import engineer_plugin

    chorus = _chorus_hr(str(tmp_path / "org"), _CancelSpyLedger(), roles=RoleRegistry())
    with pytest.raises(OrgInvariantViolation):
        chorus.hire(name="Early", role="engineer")
    chorus.workforce.register_role(engineer_plugin())
    assert chorus.hire(name="Ada", role="engineer").role == "engineer"


def _chorus_io(ledger: Ledger) -> Chorus:
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
    ledger = open_test_ledger()
    try:
        chorus = _chorus_io(ledger)
        chorus.hire(name="Boss", role="frontend_engineer")
        chorus.hire(name="Alice", role="frontend_engineer", reports_to="boss")
        org = str(tmp_path / "org")
        assert chorus.workforce.export(org) == 2

        fresh = open_test_ledger()
        try:
            assert _chorus_io(fresh).workforce.import_(org) == 2
            alice = fresh.employees.get("alice")
            assert alice is not None and alice.reports_to == "boss"
        finally:
            fresh.close()
    finally:
        ledger.close()
