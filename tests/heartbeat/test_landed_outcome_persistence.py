"""Phase 0 durability — the landed outcome survives the beat as a durable row, not just an event.

The scheduler derives the typed landing phase once at the choke point. Publishing it is
observability; *persisting* it is what lets the next beat on the same task read back why the
previous attempt landed as it did. These tests pin the persistence half of that contract.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from dream.contracts.strategy import LandedPhase

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import ExecutionMode, Ledger, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-17T12:00:00+00:00")


class _PassingBeat:
    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(passed=True, outcome={"message": "shipped"}, summary="ok")


class _Workforce:
    def __init__(self, employee: Employee) -> None:
        self._employee = employee

    def get(self, employee_id: str) -> Employee:
        assert employee_id == self._employee.id
        return self._employee


async def _run_one_beat(
    ledger: Ledger,
    *,
    employee: Employee,
    task_id: str,
    run_id: str,
    event_bus: object | None,
) -> None:
    assert ledger.tasks.checkout(task_id, employee_id=employee.id, run_id=run_id)
    ledger.wakes.enqueue(
        Wake(
            id=uid("w"),
            employee_id=employee.id,
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    scheduler = Scheduler(
        ledger=ledger,
        workforce=_Workforce(employee),
        beat_runner=_PassingBeat(),
        event_bus=event_bus,
    )
    await scheduler.run_beat(wake, run_id=run_id, now=_NOW)


async def test_landed_outcome_is_persisted_on_the_run(ledger: Ledger) -> None:
    """The typed phase is readable from the run row after the beat — the cross-beat carrier."""
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="backend_engineer"))
    task_id = uid("t-persist")
    run_id = uid("run-persist")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.dod.create(task_id, Verifier.command("true"))

    await _run_one_beat(ledger, employee=employee, task_id=task_id, run_id=run_id, event_bus=None)

    run = ledger.runs.get(run_id)
    assert run is not None
    landed = run.outcome["landed"]
    assert landed["phase"] == LandedPhase.TERMINAL_PASS.value
    assert landed["passed"] is True
    assert landed["recovery_hint"] == "none"


async def test_persistence_does_not_need_an_event_bus(ledger: Ledger) -> None:
    """Durable state must not depend on an observer being attached.

    ``event_bus=None`` above already exercises this; asserting it explicitly pins the separation so
    a future refactor cannot quietly re-couple persistence to emission.
    """
    employee = ledger.employees.create(Employee(id="e2", name="e2", role="backend_engineer"))
    task_id = uid("t-nobus")
    run_id = uid("run-nobus")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id="e2")
    )
    ledger.dod.create(task_id, Verifier.command("true"))

    await _run_one_beat(ledger, employee=employee, task_id=task_id, run_id=run_id, event_bus=None)

    run = ledger.runs.get(run_id)
    assert run is not None
    assert run.outcome["landed"]["phase"] == LandedPhase.TERMINAL_PASS.value


async def test_landed_merge_preserves_the_dream_verdict(ledger: Ledger) -> None:
    """``record_landed`` merges — it must not clobber the verdict ``finish`` already wrote."""
    employee = ledger.employees.create(Employee(id="e3", name="e3", role="backend_engineer"))
    task_id = uid("t-merge")
    run_id = uid("run-merge")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id="e3")
    )
    ledger.dod.create(task_id, Verifier.command("true"))

    await _run_one_beat(ledger, employee=employee, task_id=task_id, run_id=run_id, event_bus=None)

    run = ledger.runs.get(run_id)
    assert run is not None
    # dream's raw payload survives alongside the landed record — the two describe one beat from
    # different angles, and the projector reads both.
    assert run.outcome["message"] == "shipped"
    assert run.outcome["landed"]["phase"] == LandedPhase.TERMINAL_PASS.value


async def test_delegated_parent_persists_delegated_phase(ledger: Ledger) -> None:
    """A parked hand-off records DELEGATED — not a terminal verdict the next beat would misread."""
    employee = ledger.employees.create(Employee(id="mgr", name="mgr", role="backend_engineer"))
    parent_id = uid("t-parent")
    child_id = uid("t-child")
    run_id = uid("run-deleg")
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

    await _run_one_beat(ledger, employee=employee, task_id=parent_id, run_id=run_id, event_bus=None)

    run = ledger.runs.get(run_id)
    assert run is not None
    landed = run.outcome["landed"]
    assert landed["phase"] == LandedPhase.DELEGATED.value
    assert landed["passed"] is None
    assert landed["recovery_hint"] == "wait_for_children"


async def test_record_landed_is_idempotent_on_repeat(ledger: Ledger) -> None:
    """A second write of the same key overwrites cleanly rather than nesting or duplicating."""
    employee = ledger.employees.create(Employee(id="e4", name="e4", role="backend_engineer"))
    task_id = uid("t-twice")
    run_id = uid("run-twice")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id="e4")
    )
    ledger.dod.create(task_id, Verifier.command("true"))

    await _run_one_beat(ledger, employee=employee, task_id=task_id, run_id=run_id, event_bus=None)
    ledger.runs.record_landed(run_id, {"phase": LandedPhase.NEEDS_REWORK.value, "passed": False})

    run = ledger.runs.get(run_id)
    assert run is not None
    assert run.outcome["landed"] == {"phase": LandedPhase.NEEDS_REWORK.value, "passed": False}
    assert run.outcome["message"] == "shipped"
