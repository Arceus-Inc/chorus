"""M1 crash-safety: a beat killed mid-run is reaped, re-dispatched, and completes (spec 02 §6-§9).

The durable residue of a crash is a ``running`` run whose lease has passed, with the task still
locked under that dead run. A fresh tick must, with no manual intervention: reap the orphan (release
the locks, mark it ``timed_out``), recover the stranded task (enqueue one continuation wake, owner
preserved), then re-dispatch it — and the retried beat lands the task ``done``. This is the M1
acceptance ("kill mid-run, restart, the lease-recovery pass re-dispatches; no stranded sweeper").
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.heartbeat import Scheduler
from chorus.heartbeat._beat import BeatOutcome
from chorus.ledger import RunStatus, SqliteLedger, Task, TaskStatus
from chorus.ledger._models import Run
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
_PAST = _NOW - timedelta(seconds=60)  # a lease that expired before "now" — the crash signature


class _RecoveryBeat:
    """A :class:`BeatRunner` that passes — stands in for the retried (post-crash) beat."""

    def __init__(self) -> None:
        self.calls = 0

    async def run_task(
        self, *, task_id: str, intent: str, verification: object = (), observer: object = None
    ) -> BeatOutcome:
        self.calls += 1
        return BeatOutcome(passed=True, outcome={}, summary="recovered")


async def test_crashed_beat_is_reaped_then_redispatched_to_done(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    # Durable post-crash state: t1 is in_progress, locked under a dead run whose lease has passed.
    ledger.tasks.submit(
        Task(
            id="t1",
            intent="ship the fix",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
            checkout_run_id="run_dead",
            execution_run_id="run_dead",
        )
    )
    ledger.runs.create(
        Run(
            id="run_dead",
            employee_id="ada",
            task_id="t1",
            status=RunStatus.RUNNING,
            lease_expires_at=_PAST,
        )
    )

    beat = _RecoveryBeat()
    scheduler = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        clock=lambda: _NOW,  # the dead run's lease is expired relative to this
        max_concurrent_runs=1,
    )

    # One pulse does it all: reap → recover (re-wake) → dispatch the retry.
    for _ in range(3):  # a few pulses for headroom; it should converge on the first
        await scheduler.tick_once()
        await scheduler.drain()
        if ledger.tasks.get("t1").status is TaskStatus.DONE:  # type: ignore[union-attr]
            break

    # the crash was recovered, not retried-as-the-same-run
    dead = ledger.runs.get("run_dead")
    assert dead is not None and dead.status is RunStatus.TIMED_OUT  # reaped, not left RUNNING
    # exactly one retry beat ran, and the task completed
    assert beat.calls == 1
    assert ledger.tasks.get("t1").status is TaskStatus.DONE  # type: ignore[union-attr]
    # a fresh, succeeded run exists distinct from the dead one
    runs = ledger.runs.for_task("t1")
    assert any(r.status is RunStatus.SUCCEEDED and r.id != "run_dead" for r in runs)
