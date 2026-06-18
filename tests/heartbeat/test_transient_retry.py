"""A transient (retryable) beat fault auto-retries before stranding the task (spec 05 §5).

A ``*HeadParseError`` blip — the model emitting unparseable structured output — is marked
``retryable`` by the adapter. The scheduler re-runs such a beat up to ``transient_retries`` times
before it strands the task onto the recovery ladder. A non-retryable engine fault strands on the
first fault, with no retry.
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import RunStatus, SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


class _FlakyBeat:
    """ERRORED for the first ``fail_times`` calls, then PASSED — records its call count."""

    def __init__(self, *, fail_times: int, retryable: bool = True) -> None:
        self._fail_times = fail_times
        self._retryable = retryable
        self.calls = 0

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None, run_id: str | None = None
    ) -> BeatOutcome:
        self.calls += 1
        if self.calls <= self._fail_times:
            return BeatOutcome(
                passed=False,
                disposition=BeatDisposition.ERRORED,
                outcome={"error": "PlannerHeadParseError('missing <spec>')", "phase": None},
                retryable=self._retryable,
            )
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _dispatch(ledger: SqliteLedger, beat: _FlakyBeat, *, transient_retries: int = 2) -> Scheduler:
    employee = ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO, assignee_employee_id="e1"))
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="e1", reason=WakeReason.MANUAL, payload={"task_id": "t1"})
    )
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(employee),
        beat_runner=beat,
        transient_retries=transient_retries,
        max_concurrent_runs=1,
    )


async def test_retryable_fault_retries_until_it_passes(ledger: SqliteLedger) -> None:
    beat = _FlakyBeat(fail_times=2)  # two blips, then clean
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 3  # 1 attempt + 2 retries
    assert ledger.runs.for_task("t1")[-1].status is RunStatus.SUCCEEDED
    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]


async def test_retryable_fault_strands_after_the_budget(ledger: SqliteLedger) -> None:
    beat = _FlakyBeat(fail_times=99)  # never recovers
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 3  # capped at 1 + 2 retries
    assert ledger.runs.for_task("t1")[-1].status is RunStatus.FAILED
    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]


async def test_non_retryable_fault_is_not_retried(ledger: SqliteLedger) -> None:
    beat = _FlakyBeat(fail_times=99, retryable=False)
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 1  # stranded on the first fault, no retry
    assert ledger.tasks.get("t1").status is TaskStatus.BLOCKED  # type: ignore[union-attr]
