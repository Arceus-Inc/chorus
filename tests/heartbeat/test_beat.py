"""The beat — one employee's ``dream.run_task`` invocation, landed to the ledger (spec 03 §3).

A beat is born from a claimed wake and dies on completion: rehydrate the employee, mint the run row
(``begin_execution`` — the execution lock the checkout already points at), call the one dream seam,
land the verdict, set the task's terminal status, release the lock, fire the downstream wakes, and
mark the wake done. dream is kept behind the :class:`~chorus.heartbeat._beat.BeatRunner` Protocol so
a beat is testable with a fake — no LLM, no worktree.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome, BeatRunner
from chorus.ledger import SqliteLedger, Task
from chorus.ledger._models import DodStatus, RunStatus, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    """A stand-in :class:`BeatRunner` that records its call and returns a canned verdict."""

    def __init__(self, *, passed: bool, outcome: dict[str, object] | None = None) -> None:
        self._passed = passed
        self._outcome = outcome or {}
        self.calls: list[dict[str, object]] = []

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None
    ) -> BeatOutcome:
        self.calls.append({"task_id": task_id, "intent": intent, "observer": observer})
        return BeatOutcome(passed=self._passed, outcome=self._outcome, summary="done")


class _FakeWorkforce:
    """A minimal :class:`~chorus.workforce.Workforce` — only ``get`` is exercised by a beat."""

    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _wired(
    ledger: SqliteLedger, beat: BeatRunner, *, eid: str = "e1"
) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(Employee(id=eid, name=eid, role="engineer")),
        beat_runner=beat,
    )


def _setup_task(
    ledger: SqliteLedger, *, tid: str = "t1", eid: str = "e1", run_id: str = "r1"
) -> Wake:
    """Mirror what the tick does before a beat: employee + assigned todo, checked out, wake claimed."""
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.tasks.submit(Task(id=tid, intent=f"do {tid}", assignee_employee_id=eid))
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    assert ledger.tasks.checkout(tid, employee_id=eid, run_id=run_id)
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid})
    )
    (claimed,) = ledger.wakes.claim(limit=1)
    return claimed


async def test_passed_beat_marks_task_done(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.DONE


async def test_failed_beat_blocks_task(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


async def test_beat_mints_running_run_with_lease(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    run = ledger.runs.get("r1")
    assert run is not None
    assert run.task_id == "t1"
    assert run.wake_id == "w1"
    assert run.lease_expires_at is not None and run.lease_expires_at > _NOW
    assert run.status is RunStatus.SUCCEEDED  # finished by the time the beat returns


async def test_failed_beat_finishes_run_failed(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    run = ledger.runs.get("r1")
    assert run is not None
    assert run.status is RunStatus.FAILED


async def test_beat_releases_locks(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.checkout_run_id is None
    assert task.execution_run_id is None


async def test_beat_marks_wake_done(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    done = ledger.wakes.get("w1")
    assert done is not None
    assert done.status.value == "done"
    assert ledger.wakes.queued() == []


async def test_passed_beat_records_dod_verdict(ledger: SqliteLedger) -> None:
    eid, tid = "e1", "t1"
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.tasks.submit(Task(id=tid, intent="ship it", assignee_employee_id=eid))
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    ledger.dod.create(tid, _command_verifier())
    assert ledger.tasks.checkout(tid, employee_id=eid, run_id="r1")
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid})
    )
    (wake,) = ledger.wakes.claim(limit=1)
    sched = _wired(ledger, _FakeBeat(passed=True, outcome={"pr": "#7"}))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    dod = ledger.dod.get_for_task(tid)
    assert dod is not None
    assert dod.status is DodStatus.PASSED


async def test_passed_beat_fires_downstream_deps_resolved(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)  # t1 assigned to e1, checked out
    # A dependent t2 (assigned to e2) waits on t1 — completing t1 should wake e2.
    ledger.employees.create(Employee(id="e2", name="e2", role="engineer"))
    ledger.tasks.submit(Task(id="t2", intent="after t1", assignee_employee_id="e2"))
    ledger.tasks.set_status("t2", TaskStatus.TODO)
    ledger.dependencies.add("t2", "t1")
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    downstream = ledger.wakes.queued(employee_id="e2")
    assert len(downstream) == 1
    assert downstream[0].reason is WakeReason.DEPS_RESOLVED
    assert downstream[0].payload["task_id"] == "t2"


async def test_failed_beat_fires_no_downstream(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    ledger.employees.create(Employee(id="e2", name="e2", role="engineer"))
    ledger.tasks.submit(Task(id="t2", intent="after t1", assignee_employee_id="e2"))
    ledger.tasks.set_status("t2", TaskStatus.TODO)
    ledger.dependencies.add("t2", "t1")
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    assert ledger.wakes.queued(employee_id="e2") == []


async def test_beat_passes_task_intent_to_dream(ledger: SqliteLedger) -> None:
    wake = _setup_task(ledger)
    beat = _FakeBeat(passed=True)
    sched = _wired(ledger, beat)
    await sched.run_beat(wake, run_id="r1", now=_NOW)
    assert len(beat.calls) == 1
    assert beat.calls[0]["task_id"] == "t1"
    assert beat.calls[0]["intent"] == "do t1"


def _command_verifier() -> object:
    from chorus.outcomes import Verifier

    return Verifier.command("pytest -q")
