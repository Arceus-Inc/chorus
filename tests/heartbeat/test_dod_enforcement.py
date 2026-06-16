"""The beat enforces the task's DoD: run_beat hands the Command checks to the runner (spec 04 §1)."""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import VerificationStep, Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _RecordingBeat:
    """A beat runner that records the verification it was handed."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.verification: tuple[VerificationStep, ...] | None = None

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        observer: object = None,
    ) -> BeatOutcome:
        self.calls.append(task_id)
        self.verification = verification
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _seed(ledger: SqliteLedger) -> Employee:
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(
        Task(id="t1", intent="ship", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="e1", reason=WakeReason.TASK_ASSIGNED, payload={"task_id": "t1"})
    )
    return employee


async def _tick(ledger: SqliteLedger, beat: _RecordingBeat, employee: Employee) -> None:
    sched = Scheduler(
        ledger=ledger, workforce=_FakeWorkforce(employee), beat_runner=beat, max_concurrent_runs=1
    )
    await sched.tick(_NOW)
    await sched.drain()


async def test_run_beat_passes_the_command_dod_as_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.command("pytest -q && ruff check ."))
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.calls == ["t1"]
    assert beat.verification == (VerificationStep(command="pytest -q && ruff check ."),)


async def test_run_beat_with_no_dod_passes_no_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)  # no DoD created
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.verification == ()


async def test_run_beat_with_a_human_approval_dod_passes_no_verification(ledger: SqliteLedger) -> None:
    employee = _seed(ledger)
    ledger.dod.create("t1", Verifier.human_approval())  # not an objective check
    beat = _RecordingBeat()

    await _tick(ledger, beat, employee)

    assert beat.verification == ()
