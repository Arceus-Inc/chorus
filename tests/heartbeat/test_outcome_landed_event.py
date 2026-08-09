"""Phase 0 — the scheduler emits outcome.landed with typed phase payload."""

from __future__ import annotations

from datetime import datetime

import pytest
from dream.contracts.strategy import LandedPhase

from chorus.events import EventKind
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import ExecutionMode, Ledger, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-17T12:00:00+00:00")


class _Recorder:
    def __init__(self) -> None:
        self.events = []

    def emit(self, event: object) -> None:
        self.events.append(event)


class _PassingBeat:
    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _Workforce:
    def __init__(self, employee: Employee) -> None:
        self._employee = employee

    def get(self, employee_id: str) -> Employee:
        assert employee_id == self._employee.id
        return self._employee


async def test_passed_beat_emits_outcome_landed(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="backend_engineer"))
    task_id = uid("t-pass")
    run_id = uid("run-1")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    assert ledger.tasks.checkout(task_id, employee_id="e1", run_id=run_id)
    wake_id = uid("w1")
    ledger.wakes.enqueue(
        Wake(
            id=wake_id,
            employee_id="e1",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_PassingBeat(),
        event_bus=recorder,
    )

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    landed = [event for event in recorder.events if event.kind is EventKind.OUTCOME_LANDED]
    assert len(landed) == 1
    assert landed[0].payload["phase"] == LandedPhase.TERMINAL_PASS.value
    assert landed[0].payload["passed"] is True
    assert landed[0].payload["recovery_hint"] == "none"


async def test_delegated_parent_emits_delegated_phase(ledger: Ledger) -> None:
    """Parked delegation hand-off emits DELEGATED, not a terminal fail."""
    employee = ledger.employees.create(Employee(id="mgr", name="mgr", role="backend_engineer"))
    parent_id = uid("t-parent")
    child_id = uid("t-child")
    run_id = uid("run-d")
    ledger.tasks.submit(
        Task(
            id=parent_id,
            intent="ship feature",
            status=TaskStatus.TODO,
            assignee_employee_id="mgr",
            execution_mode=ExecutionMode.DELEGATION,
        )
    )
    ledger.tasks.submit(
        Task(
            id=child_id,
            intent="do part",
            status=TaskStatus.TODO,
            parent_id=parent_id,
            assignee_employee_id="mgr",
        )
    )
    ledger.dod.create(parent_id, Verifier.command("true"))
    assert ledger.tasks.checkout(parent_id, employee_id="mgr", run_id=run_id)
    wake_id = uid("w-d")
    ledger.wakes.enqueue(
        Wake(
            id=wake_id,
            employee_id="mgr",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": parent_id},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_PassingBeat(),
        event_bus=recorder,
    )

    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)

    parent = ledger.tasks.get(parent_id)
    assert parent is not None and parent.status is TaskStatus.BLOCKED
    landed = [event for event in recorder.events if event.kind is EventKind.OUTCOME_LANDED]
    assert len(landed) == 1
    assert landed[0].payload["phase"] == LandedPhase.DELEGATED.value
    assert landed[0].payload["passed"] is None
    assert landed[0].payload["recovery_hint"] == "wait_for_children"
