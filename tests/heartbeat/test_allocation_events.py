"""CP-1 — allocation transitions are events, not inference (OBS P6).

Who claimed what, which task started, and what the budget gate refused are ledger transitions
the scheduler already makes; this pins that each one is mirrored onto the bus with the actor,
the work unit, and the trace — so the allocation board animates from the spine instead of
re-deriving state from run text.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.events import Event, EventKind
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _Recorder:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def kinds(self) -> list[EventKind]:
        return [event.kind for event in self.events]


class _QuietBeat:
    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={}, summary="done")


class _Workforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {employee.id: employee for employee in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


class _DenyAllBudget:
    """A budget enforcer stub whose invocation gate always refuses."""

    def invocation_block(self, employee_id: str, *, now: datetime) -> object:
        return object()

    def on_cost_event(self, event: object, *, now: datetime) -> None:  # pragma: no cover
        return None


def _ready_task(ledger: Ledger, *, eid: str, handle: str) -> str:
    task_id = uid(handle)
    ledger.tasks.submit(Task(id=task_id, intent=f"do {handle}", assignee_employee_id=eid))
    ledger.tasks.set_status(task_id, TaskStatus.TODO)
    ledger.wakes.enqueue(
        Wake(
            id=uid(f"w-{handle}"),
            employee_id=eid,
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )
    return task_id


async def test_dispatch_emits_wake_claimed_and_task_status(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    task_id = _ready_task(ledger, eid="ada", handle="alloc-t1")
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_QuietBeat(),
        event_bus=recorder,
    )

    await scheduler.tick(now=_NOW)
    await scheduler.drain()

    claimed = [event for event in recorder.events if event.kind is EventKind.WAKE_CLAIMED]
    assert len(claimed) == 1
    assert claimed[0].employee_id == "ada"
    assert claimed[0].task_id == task_id
    assert claimed[0].trace_id == task_id  # root task is its own trace
    assert claimed[0].payload["reason"] == "task_assigned"

    started = [
        event
        for event in recorder.events
        if event.kind is EventKind.TASK_STATUS and event.payload.get("to") == "in_progress"
    ]
    assert len(started) == 1
    assert started[0].task_id == task_id
    assert started[0].run_id is not None


async def test_budget_gate_denial_is_an_event(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    _ready_task(ledger, eid="ada", handle="alloc-denied")
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_QuietBeat(),
        event_bus=recorder,
        budget_enforcer=_DenyAllBudget(),
    )

    report = await scheduler.tick(now=_NOW)

    assert report.budget_gated == 1
    denied = [event for event in recorder.events if event.kind is EventKind.BUDGET_HARD_STOP]
    assert len(denied) == 1
    assert denied[0].employee_id == "ada"
    assert denied[0].payload["gate"] == "dispatch"
    assert EventKind.WAKE_CLAIMED not in recorder.kinds()  # refused before any claim


async def test_facade_submit_emits_intake_events(ledger: Ledger) -> None:
    """The front door mirrors intake: task.created (+task.assigned) + wake.enqueued (OBS P6)."""
    from chorus.facade import Caps, Chorus
    from chorus.observability import EventBus, LedgerInspector
    from chorus.roles import RoleRegistry, default_roles
    from chorus.workforce._ledger import LedgerWorkforce

    recorder = _Recorder()
    bus = EventBus()
    bus.subscribe(recorder.emit)
    org = Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=bus,
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )
    org.hire(name="Ada", role="backend_engineer")
    recorder.events.clear()  # intake events only — hire has its own vocabulary

    task = org.submit("build the login page", assignee="ada")

    kinds = recorder.kinds()
    assert EventKind.TASK_CREATED in kinds
    assert EventKind.TASK_ASSIGNED in kinds
    assert EventKind.WAKE_ENQUEUED in kinds
    created = next(e for e in recorder.events if e.kind is EventKind.TASK_CREATED)
    assert created.task_id == task.id
    assert created.trace_id == task.id  # intake tasks are lineage roots
    assigned = next(e for e in recorder.events if e.kind is EventKind.TASK_ASSIGNED)
    assert assigned.employee_id == "ada"


async def test_reaped_stale_lease_emits_run_stalled(ledger: Ledger) -> None:
    """The watchdog (OBS §5): a reaped orphan lease surfaces as run.stalled — a red lane,
    not a silent recovery counter."""
    from datetime import UTC, datetime, timedelta

    from chorus.ledger._models import Run, RunStatus

    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    task_id = uid("stall-t")
    run_id = uid("stall-r")
    ledger.tasks.submit(Task(id=task_id, intent="stuck work", assignee_employee_id="ada"))
    ledger.tasks.set_status(task_id, TaskStatus.TODO)
    assert ledger.tasks.checkout(task_id, employee_id="ada", run_id=run_id)
    ledger.runs.create(
        Run(
            id=run_id,
            employee_id="ada",
            task_id=task_id,
            status=RunStatus.RUNNING,
            lease_expires_at=datetime.now(UTC) - timedelta(minutes=10),  # long dead
            started_at=datetime.now(UTC) - timedelta(minutes=20),
        )
    )
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(),
        beat_runner=_QuietBeat(),
        event_bus=recorder,
    )

    await scheduler.tick(now=datetime.now(UTC))

    stalled = [event for event in recorder.events if event.kind is EventKind.RUN_STALLED]
    assert len(stalled) == 1
    assert stalled[0].run_id == run_id
    assert stalled[0].task_id == task_id
    assert stalled[0].employee_id == "ada"
    assert stalled[0].trace_id == task_id
