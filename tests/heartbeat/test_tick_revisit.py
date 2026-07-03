"""The tick's revisit sweep — reopen decisions past their window each pulse (pm design doc §13).

A deterministic maintenance pass (peer of the recovery sweep): every tick, a decision older than the
scheduler's revisit window is reopened as a fresh problem for its owner. Idempotent, so re-ticking never
re-reopens. The sweep mechanics are unit-tested in ``tests/lifecycle/test_revisit_sweep.py``; this wires
it into the kernel pulse.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import DecisionRecord
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-07-04T12:00:00+00:00")


class _FakeBeat:
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
        return BeatOutcome(passed=True, outcome={}, summary="done")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _wired(ledger: SqliteLedger, *employees: Employee) -> Scheduler:
    return Scheduler(
        max_concurrent_runs=4,
        ledger=ledger,
        workforce=_FakeWorkforce(*employees),
        beat_runner=_FakeBeat(),
    )


def _seed_aged_decision(
    ledger: SqliteLedger, *, dec_id: str, task_id: str, owner: str, age_days: int
) -> None:
    ledger.tasks.submit(
        Task(
            id=task_id, intent="decide next bet", status=TaskStatus.DONE, assignee_employee_id=owner
        )
    )
    ledger.decisions.create(
        DecisionRecord(
            id=dec_id,
            task_id=task_id,
            option="Build live presence indicators",
            rationale="run opacity is the top complaint",
            confidence=0.8,
            outcome_metric="'stuck' tickets drop 30%",
            revisit_trigger="if flat in 2 weeks, reopen",
            created_at=_NOW - timedelta(days=age_days),
        )
    )


async def test_tick_reopens_a_decision_past_its_window(ledger: SqliteLedger) -> None:
    pm = ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
    _seed_aged_decision(ledger, dec_id="dec_old", task_id="t-old", owner="piper", age_days=20)

    report = await _wired(ledger, pm).tick(_NOW)

    assert report.decisions_reopened == 1
    assert ledger.tasks.get("revisit-dec_old") is not None


async def test_tick_leaves_a_recent_decision_alone(ledger: SqliteLedger) -> None:
    pm = ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
    _seed_aged_decision(ledger, dec_id="dec_new", task_id="t-new", owner="piper", age_days=3)

    report = await _wired(ledger, pm).tick(_NOW)

    assert report.decisions_reopened == 0
    assert ledger.tasks.get("revisit-dec_new") is None


async def test_re_ticking_does_not_reopen_twice(ledger: SqliteLedger) -> None:
    pm = ledger.employees.create(Employee(id="piper", name="Piper", role="pm"))
    _seed_aged_decision(ledger, dec_id="dec_old", task_id="t-old", owner="piper", age_days=20)
    sched = _wired(ledger, pm)

    first = await sched.tick(_NOW)
    second = await sched.tick(_NOW + timedelta(hours=1))

    assert first.decisions_reopened == 1
    assert second.decisions_reopened == 0  # idempotent across pulses
