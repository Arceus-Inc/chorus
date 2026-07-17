"""CP-1 — the trace spine: every event and cost row names its trace (OBS §3, spec 08 §6).

``trace_id`` is the ROOT task id of the beat's lineage — the id podium maps to its run
(``runs.engine_task_id``), so one trace threads podium run → chorus beats → dream spans.
The scheduler stamps it at the observer choke point (``_TraceStamper``), so every runner —
real or fake — emits stamped events without knowing about tracing. Cost events carry the
same trace as a stored column (migration ``0003_cost_event_trace``).
"""

from __future__ import annotations

from datetime import UTC, datetime

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
    """An EventSink that keeps every event."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)


class _EmittingBeat:
    """A runner that emits one BARE event through its observer — the stamper must fill it."""

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
        if callable(observer):
            observer(Event(kind=EventKind.RUN_TEXT, at=datetime.now(UTC), payload={"text": "hi"}))
        return BeatOutcome(passed=True, outcome={}, summary="done", cost_cents=7, model="gpt-x")


class _Workforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {employee.id: employee for employee in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _lineage(ledger: Ledger, *, eid: str) -> tuple[str, str]:
    """A root task with an assigned, wake-queued CHILD — the beat runs the child."""
    root_id, child_id = uid("trace-root"), uid("trace-child")
    ledger.tasks.submit(Task(id=root_id, intent="the objective"))
    ledger.tasks.submit(
        Task(id=child_id, intent="one part", parent_id=root_id, assignee_employee_id=eid)
    )
    ledger.tasks.set_status(child_id, TaskStatus.TODO)
    ledger.wakes.enqueue(
        Wake(id=uid("w1"), employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": child_id})
    )
    return root_id, child_id


async def test_dispatch_stamps_trace_run_and_employee_on_every_event(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    root_id, child_id = _lineage(ledger, eid=employee.id)
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_EmittingBeat(),
        event_bus=recorder,
    )

    await scheduler.tick(now=_NOW)
    await scheduler.drain()

    texts = [event for event in recorder.events if event.kind is EventKind.RUN_TEXT]
    assert len(texts) == 1
    stamped = texts[0]
    assert stamped.trace_id == root_id  # the ROOT of the lineage, not the beat's own task
    assert stamped.task_id == child_id
    assert stamped.employee_id == "ada"
    assert stamped.run_id is not None
    assert stamped.payload == {"text": "hi"}  # stamping never rewrites the payload


async def test_cost_event_carries_the_same_trace(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    root_id, child_id = _lineage(ledger, eid=employee.id)
    scheduler = Scheduler(
        ledger=ledger, workforce=_Workforce(employee), beat_runner=_EmittingBeat()
    )

    await scheduler.tick(now=_NOW)
    await scheduler.drain()

    run_rows = ledger.runs.for_task(child_id)
    assert len(run_rows) == 1
    costs = ledger.cost_events.for_run(run_rows[0].id)
    assert len(costs) == 1
    assert costs[0].task_id == child_id
    assert costs[0].trace_id == root_id


async def test_a_root_task_is_its_own_trace(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    task_id = uid("solo")
    ledger.tasks.submit(Task(id=task_id, intent="solo work", assignee_employee_id="ada"))
    ledger.tasks.set_status(task_id, TaskStatus.TODO)
    ledger.wakes.enqueue(
        Wake(id=uid("w2"), employee_id="ada", reason=WakeReason.TASK_ASSIGNED, payload={"task_id": task_id})
    )
    recorder = _Recorder()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_EmittingBeat(),
        event_bus=recorder,
    )

    await scheduler.tick(now=_NOW)
    await scheduler.drain()

    texts = [event for event in recorder.events if event.kind is EventKind.RUN_TEXT]
    assert texts and texts[0].trace_id == task_id
