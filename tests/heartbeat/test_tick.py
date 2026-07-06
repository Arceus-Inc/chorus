"""The tick loop — one kernel pulse: recover → dispatch, capped by concurrency (spec 03 §3d, §5).

A tick is a pure function of the ledger (B2.2): it reaps stale leases, then claims queued wakes in
the deterministic dispatch order and kicks each beat off async — capped by the free concurrency
budget, serialized to ≤1 live beat per employee, gated by the checkout compare-and-swap. Dispatch is
non-blocking, so the assertions ``await sched.drain()`` to let the in-flight beats land first.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome, BeatRunner
from chorus.ledger import SqliteLedger, Task
from chorus.ledger._models import Run, RunStatus, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    """A stand-in :class:`BeatRunner` that records its calls and returns a canned verdict."""

    def __init__(self, *, passed: bool = True) -> None:
        self._passed = passed
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
        return BeatOutcome(passed=self._passed, outcome={}, summary="done")


class _FakeWorkforce:
    """A minimal :class:`~chorus.workforce.Workforce` — only ``get`` is exercised by a beat."""

    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _wired(
    ledger: SqliteLedger,
    beat: BeatRunner,
    *employees: Employee,
    max_concurrent_runs: int = 4,
) -> Scheduler:
    return Scheduler(
        max_concurrent_runs=max_concurrent_runs,
        ledger=ledger,
        workforce=_FakeWorkforce(*employees),
        beat_runner=beat,
    )


def _employee(ledger: SqliteLedger, eid: str) -> Employee:
    return ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def _assigned(ledger: SqliteLedger, *, tid: str, eid: str, wid: str) -> None:
    """An assigned, dispatch-ready task + its queued ``task_assigned`` wake (NOT yet checked out)."""
    ledger.tasks.submit(Task(id=tid, intent=f"do {tid}", assignee_employee_id=eid))
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    ledger.wakes.enqueue(
        Wake(id=wid, employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid})
    )


async def test_tick_dispatches_eligible_task_through_a_full_beat(ledger: SqliteLedger) -> None:
    e1 = _employee(ledger, "e1")
    _assigned(ledger, tid="t1", eid="e1", wid="w1")
    beat = _FakeBeat(passed=True)
    sched = _wired(ledger, beat, e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert beat.calls == ["t1"]
    assert report.wakes_dispatched == 1
    assert report.beats_started == 1
    task = ledger.tasks.get("t1")
    assert task is not None and task.status is TaskStatus.DONE
    done = ledger.wakes.get("w1")
    assert done is not None and done.status.value == "done"


async def test_tick_mints_a_run_per_dispatched_beat(ledger: SqliteLedger) -> None:
    e1 = _employee(ledger, "e1")
    _assigned(ledger, tid="t1", eid="e1", wid="w1")
    sched = _wired(ledger, _FakeBeat(passed=True), e1)

    await sched.tick(_NOW)
    await sched.drain()

    runs = ledger.runs.for_task("t1")
    assert len(runs) == 1
    assert runs[0].wake_id == "w1"
    assert runs[0].status is RunStatus.SUCCEEDED


async def test_tick_respects_the_concurrency_budget(ledger: SqliteLedger) -> None:
    # One slot already burned by a live run; a cap of 2 leaves exactly one free slot.
    e1 = _employee(ledger, "e1")
    e2 = _employee(ledger, "e2")
    e3 = _employee(ledger, "e3")
    ledger.tasks.submit(Task(id="t0", intent="do t0", assignee_employee_id="e3"))
    assert ledger.tasks.checkout("t0", employee_id="e3", run_id="busy")
    ledger.runs.create(
        Run(
            id="busy",
            employee_id="e3",
            task_id="t0",
            status=RunStatus.RUNNING,
            lease_expires_at=_NOW + timedelta(seconds=300),
        )
    )
    _assigned(ledger, tid="t1", eid="e1", wid="w1")
    _assigned(ledger, tid="t2", eid="e2", wid="w2")
    sched = _wired(ledger, _FakeBeat(passed=True), e1, e2, e3, max_concurrent_runs=2)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.wakes_dispatched == 1  # only the single free slot is used
    assert report.blocked_by_budget == 1


async def test_tick_serializes_to_one_beat_per_employee(ledger: SqliteLedger) -> None:
    # Two queued wakes for the SAME employee in one tick: only one beat may start.
    e1 = _employee(ledger, "e1")
    _assigned(ledger, tid="t1", eid="e1", wid="w1")
    _assigned(ledger, tid="t2", eid="e1", wid="w2")
    sched = _wired(ledger, _FakeBeat(passed=True), e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.wakes_dispatched == 1
    # The undispatched wake is returned to ``queued`` (FIFO preserved), not stranded.
    leftover = [w for w in (ledger.wakes.get("w1"), ledger.wakes.get("w2")) if w is not None]
    statuses = sorted(w.status.value for w in leftover)
    assert statuses == ["done", "queued"]


async def test_tick_skips_a_wake_whose_task_is_already_checked_out(ledger: SqliteLedger) -> None:
    # A live owner holds t1 under another run: the checkout CAS 409s and the wake is released.
    e1 = _employee(ledger, "e1")
    _assigned(ledger, tid="t1", eid="e1", wid="w1")
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="other")
    beat = _FakeBeat(passed=True)
    sched = _wired(ledger, beat, e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.wakes_dispatched == 0
    assert beat.calls == []
    held = ledger.wakes.get("w1")
    assert held is not None and held.status.value == "queued"


async def test_tick_recovers_a_crashed_beat_before_dispatch(ledger: SqliteLedger) -> None:
    # A running run with an expired lease is crash debris; the RECOVER step reaps it this pulse.
    past = _NOW - timedelta(seconds=60)
    e1 = _employee(ledger, "e1")
    ledger.tasks.submit(Task(id="t1", intent="do t1", assignee_employee_id="e1"))
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="dead")
    ledger.runs.create(
        Run(
            id="dead",
            employee_id="e1",
            task_id="t1",
            status=RunStatus.RUNNING,
            lease_expires_at=past,
        )
    )
    sched = _wired(ledger, _FakeBeat(passed=True), e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.recovered == 1
    reaped = ledger.runs.get("dead")
    assert reaped is not None and reaped.status is RunStatus.TIMED_OUT


async def test_tick_is_quiet_when_nothing_is_queued(ledger: SqliteLedger) -> None:
    sched = _wired(ledger, _FakeBeat(passed=True))
    report = await sched.tick(_NOW)
    await sched.drain()
    assert report.recovered == 0
    assert report.wakes_dispatched == 0
    assert report.beats_started == 0
    assert report.blocked_by_budget == 0


async def test_second_tick_does_not_redispatch_a_running_beat(ledger: SqliteLedger) -> None:
    # A re-tick while a beat is still live must not double-dispatch the same task.
    e1 = _employee(ledger, "e1")
    ledger.tasks.submit(Task(id="t1", intent="do t1", assignee_employee_id="e1"))
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="live")
    ledger.runs.create(
        Run(
            id="live",
            employee_id="e1",
            task_id="t1",
            status=RunStatus.RUNNING,
            lease_expires_at=_NOW + timedelta(seconds=300),
        )
    )
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="e1", reason=WakeReason.TASK_ASSIGNED, payload={"task_id": "t1"})
    )
    beat = _FakeBeat(passed=True)
    sched = _wired(ledger, beat, e1)

    report = await sched.tick(_NOW)
    await sched.drain()

    assert report.wakes_dispatched == 0  # live owner holds the checkout; CAS 409s
    assert beat.calls == []
