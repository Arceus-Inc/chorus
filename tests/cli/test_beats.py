"""The kernel seam: ``LedgerWorkforce`` + ``SchedulerTickRunner`` driven with a fake beat runner.

No dream, no network — a fake :class:`~chorus.heartbeat.BeatRunner` stands in for the dream adapter,
so the whole tick→dispatch→land path is exercised deterministically. This proves the sync→async
bridge and the scheduler wiring without touching Azure.
"""

from __future__ import annotations

import pytest

from chorus.adapters import ModelRate, TokenPricing
from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce
from chorus_cli._beats import SchedulerTickRunner, build_beat_service

pytestmark = pytest.mark.integration


class _FakeBeat:
    """A stand-in dream adapter: records its calls, lands a fixed verdict."""

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
        return BeatOutcome(passed=self._passed, outcome={"note": "fake"}, summary="fake beat")


def _seed_assigned_wake(ledger: Ledger, *, task_id: str, employee_id: str) -> None:
    ledger.employees.create(Employee(id=employee_id, name=employee_id, role="engineer"))
    ledger.tasks.submit(Task(id=task_id, intent="ship", status=TaskStatus.TODO))
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id=employee_id,
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )


# -- build_beat_service -----------------------------------------------------------------------------


def test_build_beat_service_wires_a_scheduler(ledger: Ledger) -> None:
    # The harness is materialized lazily per beat by the factory, so no provider call happens here —
    # build_beat_service just wires the scheduler over the org factory.
    runner = build_beat_service(
        ledger,
        api_key="k",
        base_url="https://example/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        pricing=TokenPricing(rates={}, default=ModelRate(1, 1)),
    )
    assert isinstance(runner, SchedulerTickRunner)
    assert runner.model == "gpt-x"


# -- SchedulerTickRunner ----------------------------------------------------------------------------


def _runner(ledger: Ledger, beat: _FakeBeat) -> SchedulerTickRunner:
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        max_concurrent_runs=1,
    )
    return SchedulerTickRunner(scheduler, model="fake-deployment")


def test_run_tick_dispatches_a_beat_and_lands_it(ledger: Ledger) -> None:
    _seed_assigned_wake(ledger, task_id=uid("t1"), employee_id="alice")
    beat = _FakeBeat(passed=True)

    report = _runner(ledger, beat).run_tick()

    assert beat.calls == [uid("t1")]  # the beat actually ran
    assert report.beats_started == 1
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # passed → done
    runs = ledger.runs.for_task(uid("t1"))
    assert len(runs) == 1 and runs[0].status.value == "succeeded"


def test_run_tick_blocks_the_task_on_a_failed_beat(ledger: Ledger) -> None:
    _seed_assigned_wake(ledger, task_id=uid("t1"), employee_id="alice")
    beat = _FakeBeat(passed=False)

    _runner(ledger, beat).run_tick()

    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # failed → blocked


def test_run_tick_on_an_empty_ledger_reports_nothing(ledger: Ledger) -> None:
    report = _runner(ledger, _FakeBeat()).run_tick()
    assert report.beats_started == 0 and report.wakes_dispatched == 0


def test_model_is_exposed(ledger: Ledger) -> None:
    assert _runner(ledger, _FakeBeat()).model == "fake-deployment"
