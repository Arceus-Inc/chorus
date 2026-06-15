"""The kernel tick + the beat (spec 03 §3).

The tick is a **pure function of the ledger** — one loop, fixed interval, holds
no state (B2.2). Each pass runs, in order: (a) RECOVER stale leases, (b) fire
due CRON edges (double-fire-guarded), (c) drain due MONITORS, (d) DISPATCH wakes
capped by concurrency. Dispatch is **non-blocking**: the tick kicks each beat off
async and moves on, so one slow beat can't stall the pulse.

A **beat** (``run_beat``) rehydrates an employee, runs the one ``dream.run_task``
seam, writes a raw memory delta, lands the outcome, sets status, releases the
lock, and fires downstream wakes. Almost none of this is new logic — the locks,
the lease, the beat are dream; chorus's new code is the wake/routine tables,
assignment, ``fire_downstream_wakes``, and the outcome/DoD seam.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING, TypeVar

from chorus.heartbeat._wake import TickReport, Wake
from chorus.ledger import TaskPriority
from chorus.ledger._models import DodStatus, Run, RunStatus, TaskStatus

if TYPE_CHECKING:
    from chorus.heartbeat._beat import BeatRunner
    from chorus.ledger import SqliteLedger
    from chorus.observability import EventBus
    from chorus.workforce import Workforce

_T = TypeVar("_T")

# Dispatch priority rank for the deterministic sort key (spec 03 §3).
PRIORITY_RANK: dict[TaskPriority, int] = {
    TaskPriority.CRITICAL: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.MEDIUM: 2,
    TaskPriority.LOW: 3,
}


class Scheduler:
    """The push-only kernel (spec 03).

    Built on dream's coordination board (the two-lock CAS, the lease watchdog);
    the *org* scheduling — wakes, routines, fairness, the deterministic sort key
    — is chorus's own. The composition root (spec 10 §1) injects the ledger,
    wake queue, claim manager, budgets, and event bus.
    """

    def __init__(
        self,
        *,
        tick_interval_s: float = 1.0,
        max_concurrent_runs: int = 4,
        lease_ttl_s: float = 300.0,
        ledger: SqliteLedger | None = None,
        workforce: Workforce | None = None,
        beat_runner: BeatRunner | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.tick_interval_s = tick_interval_s
        self.max_concurrent_runs = max_concurrent_runs
        self.lease_ttl_s = lease_ttl_s
        self._ledger = ledger
        self._workforce = workforce
        self._beat_runner = beat_runner
        self._event_bus = event_bus

    async def tick(self, now: datetime) -> TickReport:
        """One kernel pulse — recover → cron → monitors → dispatch (spec 03 §3).

        Idempotent and re-derivable from rows, so crash + restart + re-read
        continues. In the Arceus/Postgres deployment several workers may tick the
        same ledger; every claim step is exact-once at the row level
        (``SKIP LOCKED`` + the deterministic sort key, spec 03 §5).
        """
        raise NotImplementedError("spec 03 §3: recover → cron → monitors → dispatch")

    async def run_beat(self, wake: Wake, *, run_id: str, now: datetime) -> None:
        """One employee's short ``dream.run_task`` invocation (spec 03 §3).

        The task is already checked out under ``run_id`` (the tick's dispatch CAS); the beat:
        rehydrate the employee → ``begin_execution`` (mint the ``run`` row + lease the checkout lock
        points at) → ``dream.run_task(observer=event_bus.emit)`` → land the verdict (finish the run,
        record the DoD, ``done`` on pass / ``blocked`` on fail) → release the lock → fire the
        downstream wakes (``deps_resolved`` / ``children_done``) → mark the wake done. dream is the
        only seam; everything else is a durable ledger write, re-derivable after a crash.
        """
        ledger = self._require_ledger()
        workforce = self._require(self._workforce, "workforce")
        beat_runner = self._require(self._beat_runner, "beat_runner")

        employee = workforce.get(wake.employee_id)
        task_id = str(wake.payload["task_id"])
        task = ledger.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)

        # begin_execution — mint the run row the checkout lock already points at, with a fresh lease.
        lease = now + timedelta(seconds=self.lease_ttl_s)
        ledger.runs.create(
            Run(
                id=run_id,
                employee_id=employee.id,
                task_id=task_id,
                wake_id=wake.id,
                status=RunStatus.RUNNING,
                lease_expires_at=lease,
                started_at=now,
            )
        )

        observer = self._event_bus.emit if self._event_bus is not None else None
        result = await beat_runner.run_task(
            task_id=task_id, intent=task.intent, observer=observer
        )

        verdict = result.outcome or None
        if result.passed:
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            ledger.finalize_beat(
                task_id=task_id, run_id=run_id, dod_status=DodStatus.PASSED, verdict=verdict
            )
        else:
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            ledger.finalize_beat(
                task_id=task_id, run_id=run_id, dod_status=DodStatus.FAILED, verdict=verdict
            )
            ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)

        ledger.tasks.release_locks(task_id, run_id=run_id)
        ledger.wakes.mark_done(wake.id)

    def _require_ledger(self) -> SqliteLedger:
        return self._require(self._ledger, "ledger")

    @staticmethod
    def _require(seam: _T | None, name: str) -> _T:
        if seam is None:
            raise RuntimeError(f"Scheduler not wired with a {name} (inject it at construction)")
        return seam


    @staticmethod
    def sort_key(*, in_progress: bool, deps_done: bool, priority: TaskPriority,
                 created_at: datetime, wake_id: str) -> tuple[int, int, int, datetime, str]:
        """The total, tie-broken dispatch order (spec 03 §3).

        Resume live work before new; dependency-ready before gated; priority;
        FIFO within a band (anti-starvation); ``wake_id`` as the final tie-break
        so two ticks always agree on which wake is next.
        """
        return (
            0 if in_progress else 1,
            0 if deps_done else 1,
            PRIORITY_RANK[priority],
            created_at,
            wake_id,
        )


__all__ = [
    "PRIORITY_RANK",
    "Scheduler",
]
