"""The per-employee beat-runner seam: the scheduler resolves a runner *for each employee* (spec 06 §2).

The converged kernel runs every beat as its employee — so the scheduler no longer holds one shared
runner; it asks a :class:`BeatRunnerFor` for the runner whose harness is materialized for the
dispatched employee. ``single()`` is the degenerate one-runner case (back-compat / tests).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.heartbeat._runner_for import runner_from, single
from chorus.ledger import RunStatus, SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-17T12:00:00+00:00")


class _TaggedBeat:
    """A BeatRunner that records the tasks it ran, tagged so we can tell two runners apart."""

    def __init__(self, tag: str) -> None:
        self.tag = tag
        self.calls: list[str] = []

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None, run_id: str | None = None
    ) -> BeatOutcome:
        self.calls.append(task_id)
        return BeatOutcome(passed=True, outcome={}, summary=self.tag)


class _PerEmployee:
    """A :class:`BeatRunnerFor` that hands each employee its own distinct runner."""

    def __init__(self) -> None:
        self.runners: dict[str, _TaggedBeat] = {}

    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> _TaggedBeat:
        return self.runners.setdefault(employee.id, _TaggedBeat(employee.id))


class _BrokenFactory:
    def runner_for(self, employee: Employee, *, task_id: str | None = None) -> _TaggedBeat:
        raise RecursionError("copy loop")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _seed(ledger: SqliteLedger, employee_id: str, task_id: str) -> Employee:
    employee = ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee_id)
    )
    ledger.wakes.enqueue(
        Wake(id=f"w_{task_id}", employee_id=employee_id, reason=WakeReason.TASK_ASSIGNED,
             payload={"task_id": task_id})
    )
    return employee


def test_single_returns_the_one_runner_for_any_employee() -> None:
    runner = _TaggedBeat("only")
    seam = single(runner)
    assert seam.runner_for(Employee(id="a", name="a", role="engineer")) is runner
    assert seam.runner_for(Employee(id="b", name="b", role="reviewer")) is runner


def test_runner_from_wraps_a_callable_as_the_seam() -> None:
    """A bare callable (e.g. ``factory.runner_for``) becomes a :class:`BeatRunnerFor` — the §0 form."""
    runner = _TaggedBeat("fn")
    seen: list[tuple[str, str | None]] = []

    def resolve(employee: Employee, *, task_id: str | None = None) -> _TaggedBeat:
        seen.append((employee.id, task_id))
        return runner

    seam = runner_from(resolve)
    got = seam.runner_for(Employee(id="a", name="a", role="engineer"), task_id="t1")
    assert got is runner
    assert seen == [("a", "t1")]


async def test_scheduler_resolves_a_distinct_runner_per_employee(ledger: SqliteLedger) -> None:
    ada = _seed(ledger, "ada", "t-ada")
    bob = _seed(ledger, "bob", "t-bob")
    factory = _PerEmployee()
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(ada, bob),
        beat_runner_for=factory,
        max_concurrent_runs=2,
    )

    await sched.tick(_NOW)
    await sched.drain()

    # each employee's own runner ran exactly its own task — not one shared runner
    assert factory.runners["ada"].calls == ["t-ada"]
    assert factory.runners["bob"].calls == ["t-bob"]


async def test_scheduler_still_accepts_a_single_beat_runner(ledger: SqliteLedger) -> None:
    ada = _seed(ledger, "ada", "t-ada")
    runner = _TaggedBeat("shared")
    sched = Scheduler(
        ledger=ledger, workforce=_FakeWorkforce(ada), beat_runner=runner, max_concurrent_runs=1
    )

    await sched.tick(_NOW)
    await sched.drain()

    assert runner.calls == ["t-ada"]  # back-compat: a single runner is wrapped in single()


async def test_runner_materialization_failure_is_recorded_as_failed_run(
    ledger: SqliteLedger,
) -> None:
    ada = _seed(ledger, "ada", "t-ada")
    sched = Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(ada),
        beat_runner_for=_BrokenFactory(),
        max_concurrent_runs=1,
    )

    await sched.tick(_NOW)
    await sched.drain()

    runs = ledger.runs.for_task("t-ada")
    assert len(runs) == 1
    assert runs[0].status is RunStatus.FAILED
    assert "copy loop" in str(runs[0].outcome)

    task = ledger.tasks.get("t-ada")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    assert task.checkout_run_id is None
    assert task.execution_run_id is None
    assert ledger.recovery_actions.active_for_source("t-ada") is not None
