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

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, TypeVar

from chorus.adapters._failure import failure_outcome
from chorus.cron._fire import fire_routine
from chorus.governance import GovernanceResolver
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.heartbeat._invokability import invokability_block
from chorus.heartbeat._runner_for import single
from chorus.heartbeat._wake import TickReport, Wake
from chorus.ledger import ApprovalGate, TaskPriority
from chorus.ledger._models import (
    ActivityVerb,
    Artifact,
    ArtifactType,
    CostEvent,
    DodStatus,
    Monitor,
    MonitorRecoveryPolicy,
    MonitorStatus,
    RecoveryAction,
    RecoveryKind,
    Run,
    RunStatus,
    TaskStatus,
    WakeReason,
)
from chorus.lifecycle import TERMINAL, record_activity
from chorus.memory import SprintDelta
from chorus.outcomes import DoDKind, Verifier
from chorus.recovery import reconcile

if TYPE_CHECKING:
    from dream.contracts import MemoryWriter

    from chorus.budgets import BudgetEnforcer
    from chorus.events import Event
    from chorus.heartbeat._beat import BeatRunner
    from chorus.heartbeat._runner_for import BeatRunnerFor
    from chorus.ledger import SqliteLedger, Task
    from chorus.observability import EventSink
    from chorus.outcomes import Artifact as OutcomeArtifact
    from chorus.outcomes import LanderRegistry, VerificationStep
    from chorus.roles import RoleRegistry
    from chorus.workforce import Employee, Workforce

_T = TypeVar("_T")


def _utc_now() -> datetime:
    return datetime.now(UTC)


_OUTCOME_BY_DISPOSITION: dict[BeatDisposition, str] = {
    BeatDisposition.PASSED: "done",
    BeatDisposition.DOD_FAILED: "needs_changes",
    BeatDisposition.ERRORED: "blocked",
}


def _sprint_delta(
    *, run_id: str, employee: Employee, task: Task, result: BeatOutcome, scope: str, now: datetime
) -> SprintDelta:
    """Build the beat's raw episodic record — honest fields derived from the run (spec 07 §3)."""
    verdict = result.outcome or {}
    raw_score = verdict.get("score")
    score = float(raw_score) if isinstance(raw_score, int | float) else (1.0 if result.passed else 0.0)
    return SprintDelta(
        run_id=run_id,
        task_id=task.id,
        employee_id=employee.id,
        scope=scope,
        intent=task.intent,
        outcome=_OUTCOME_BY_DISPOSITION.get(result.disposition or BeatDisposition.ERRORED, "blocked"),
        score=score,
        created_at=now,
        body=result.summary or "",
    )


def _to_ledger_artifact(artifact: OutcomeArtifact) -> Artifact:
    """Map a lander's canonical :class:`~chorus.outcomes.Artifact` to a storable ledger row."""
    return Artifact(
        id=f"art_{uuid.uuid4().hex[:12]}",
        task_id=artifact.task_id,
        type=ArtifactType(artifact.type.value),
        external_id=artifact.external_id,
        url=artifact.url,
        is_primary=artifact.is_primary,
        resource_ref=artifact.resource_ref,
    )

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
        max_repair_attempts: int = 2,
        transient_retries: int = 2,
        memory_writer: MemoryWriter | None = None,
        ledger: SqliteLedger | None = None,
        workforce: Workforce | None = None,
        beat_runner: BeatRunner | None = None,
        beat_runner_for: BeatRunnerFor | None = None,
        event_bus: EventSink | None = None,
        budget_enforcer: BudgetEnforcer | None = None,
        roles: RoleRegistry | None = None,
        landers: LanderRegistry | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self.tick_interval_s = tick_interval_s
        self.max_concurrent_runs = max_concurrent_runs
        self.lease_ttl_s = lease_ttl_s
        self.max_repair_attempts = max_repair_attempts  # DoD-failure self-repair budget (spec 04 §1)
        # In-beat retry budget for *transient* engine faults (a planner/evaluator parse blip): re-run the
        # beat this many times before stranding it onto the recovery ladder (spec 05 §5).
        self.transient_retries = transient_retries
        self._ledger = ledger
        self._workforce = workforce
        # The beat seam is per-employee (resolve a role-faithful runner for the dispatched employee). A
        # single ``beat_runner`` is the degenerate case — wrapped in ``single()`` so both inject the
        # same way (spec 06 §2).
        self._beat_runner_for = (
            beat_runner_for
            if beat_runner_for is not None
            else (single(beat_runner) if beat_runner is not None else None)
        )
        self._event_bus = event_bus
        self._budget_enforcer = budget_enforcer  # None = budgets off (gating is opt-in)
        self._roles = roles  # None = no intake DoD (a task keeps whatever DoD was set explicitly)
        self._landers = landers  # None = a passed beat lands 'done' without recording a role artifact
        self._memory_writer = memory_writer  # None = no episodic capture (the kernel is writer-agnostic)
        self._clock = clock or _utc_now  # the time source the run loop stamps each pulse with
        self._sleep = sleep or asyncio.sleep  # the inter-pulse wait (injectable for deterministic tests)
        self._stop = asyncio.Event()  # set by stop(); ends the run loop after the current pulse
        self._inflight: set[asyncio.Task[None]] = set()

    async def tick(self, now: datetime) -> TickReport:
        """One kernel pulse — recover → cron → monitors → dispatch (spec 03 §3).

        Idempotent and re-derivable from rows, so crash + restart + re-read
        continues. In the Arceus/Postgres deployment several workers may tick the
        same ledger; every claim step is exact-once at the row level
        (``SKIP LOCKED`` + the deterministic sort key, spec 03 §5).
        """
        ledger = self._require_ledger()

        # (a) RECOVER — reap orphaned leases + reconcile stranded work before any new dispatch, so
        # a crashed beat's lock is freed and its slot returned to the budget this same pulse.
        swept = reconcile(ledger, now=now)
        recovered = len(swept.reaped_runs)

        # (b) CRON — fire due routines (each firing double-fire-guarded; writes a task, never a beat).
        routines_fired = 0
        for trigger in ledger.routine_triggers.due(now=now):
            if fire_routine(ledger, trigger, now=now) is not None:
                routines_fired += 1

        # (c) MONITORS — drain deferred self-wakes; a one-shot fire wakes the owner, an exhausted
        # monitor escalates per its recovery policy instead.
        for monitor in ledger.monitors.due(now=now):
            fired = ledger.monitors.fire(monitor.id)
            if fired.status is MonitorStatus.EXHAUSTED:
                self._apply_monitor_recovery(ledger, fired)
                continue
            ledger.wakes.enqueue(
                Wake(
                    id=f"wake_{uuid.uuid4().hex[:12]}",
                    employee_id=fired.employee_id,
                    reason=WakeReason.MONITOR_DUE,
                    payload={"task_id": fired.task_id},
                )
            )

        # (d) DISPATCH — claim up to the free concurrency budget, then serialize per employee.
        free_slots = self.max_concurrent_runs - ledger.runs.count_running()
        queued_before = len(ledger.wakes.queued())
        claimed = ledger.wakes.claim(limit=free_slots) if free_slots > 0 else []
        blocked_by_budget = max(0, queued_before - free_slots)

        busy = ledger.runs.running_employee_ids()
        dispatched = 0
        budget_gated = 0
        invokability_cancelled = 0
        invokability_skipped = 0
        for wake in claimed:
            # Per-employee serialization (spec 03 §5): at most one live beat per employee. A wake we
            # can't run this pulse goes back to ``queued`` (FIFO position preserved), not stranded.
            if wake.employee_id in busy or "task_id" not in wake.payload:
                ledger.wakes.release(wake.id)
                continue
            # Dependency gate (spec 02 §2): a task with unresolved blockers is withheld. Consume this
            # wake — the blocker's completion fires a fresh ``deps_resolved`` wake that re-dispatches it.
            if ledger.dependencies.unresolved_blockers(str(wake.payload["task_id"])):
                ledger.wakes.mark_done(wake.id)
                continue
            # Stale-wake drain (spec 03 §5): a wake whose task is already terminal is discarded, not
            # re-queued. A manager fans out several deps_resolved/children_done wakes per task; once one
            # drives the integrate, the rest point at a now-``done`` task — left queued they fail the
            # checkout CAS every tick and clog the employee's one-beat-per-pulse slot, starving its
            # other work. Draining them keeps the dispatch slot live.
            stale = ledger.tasks.get(str(wake.payload["task_id"]))
            if stale is None or stale.status in TERMINAL:
                ledger.wakes.mark_done(wake.id)
                continue
            # Gate 0 (spec 06 §3): a dead, orphaned, or paused identity never starts a beat. A
            # terminal verdict cancels the wake and its task; a paused one releases it to wait.
            if self._workforce is not None:
                block = invokability_block(self._workforce, wake.employee_id)
                if block is not None:
                    if block.cancels:
                        task_id = str(wake.payload["task_id"])
                        ledger.wakes.mark_done(wake.id)
                        ledger.tasks.set_status(task_id, TaskStatus.CANCELLED)
                        invokability_cancelled += 1
                    else:
                        ledger.wakes.release(wake.id)
                        invokability_skipped += 1
                    continue
            # Gate 1 (spec 04 §3): no beat starts for a paused or over-budget scope.
            if (
                self._budget_enforcer is not None
                and self._budget_enforcer.invocation_block(wake.employee_id, now=now) is not None
            ):
                ledger.wakes.release(wake.id)
                budget_gated += 1
                continue
            task_id = str(wake.payload["task_id"])
            run_id = f"run_{uuid.uuid4().hex}"
            # Dispatch CAS (spec 03 §5): checkout flips the task to ``in_progress`` under ``run_id``.
            # A False is a 409 — a live owner already holds it — so we release the wake and skip.
            if not ledger.tasks.checkout(task_id, employee_id=wake.employee_id, run_id=run_id):
                ledger.wakes.release(wake.id)
                continue
            busy.add(wake.employee_id)
            self._dispatch_beat(wake, run_id=run_id, now=now)
            dispatched += 1

        return TickReport(
            at=now,
            recovered=recovered,
            routines_fired=routines_fired,
            wakes_dispatched=dispatched,
            beats_started=dispatched,
            blocked_by_budget=blocked_by_budget,
            budget_gated=budget_gated,
            invokability_cancelled=invokability_cancelled,
            invokability_skipped=invokability_skipped,
        )

    async def tick_once(self) -> TickReport:
        """One pulse stamped with the injected clock — the facade's manual single tick (spec 03 §3)."""
        return await self.tick(self._clock())

    async def run(self) -> None:
        """Drive ticks at ``tick_interval_s`` until :meth:`stop` (or cancellation) — the §3 cadence.

        Each pulse ticks the ledger then waits the interval. ``stop()`` ends the loop after the
        current pulse; cancellation ends it at the next ``await``. Either way the ``finally`` drains
        the in-flight beats, so shutdown never orphans a running beat. Single-use: a stopped loop
        stays stopped (construct a fresh ``Scheduler`` to run again).
        """
        try:
            while not self._stop.is_set():
                await self.tick(self._clock())
                await self._sleep(self.tick_interval_s)
        finally:
            await self.drain()

    def stop(self) -> None:
        """Signal :meth:`run` to exit after the current pulse (idempotent)."""
        self._stop.set()

    def _apply_monitor_recovery(self, ledger: SqliteLedger, monitor: Monitor) -> None:
        """An exhausted monitor escalates per its recovery policy (spec 03 §3c, spec 01 Cluster B).

        ``wake_owner`` enqueues a recovery wake to the assignee; ``create_recovery``/``escalate``
        open a first-class ``recovery_action`` (at most one open per source task) — liveness stays
        visible rather than silently lapsing when the deferred check gives up.
        """
        if monitor.recovery_policy is MonitorRecoveryPolicy.WAKE_OWNER:
            ledger.wakes.enqueue(
                Wake(
                    id=f"wake_{uuid.uuid4().hex[:12]}",
                    employee_id=monitor.employee_id,
                    reason=WakeReason.RECOVERY,
                    payload={"task_id": monitor.task_id, "cause": "monitor_exhausted"},
                )
            )
            return
        if ledger.recovery_actions.active_for_source(monitor.task_id) is not None:
            return
        kind = (
            RecoveryKind.GRAPH_LIVENESS
            if monitor.recovery_policy is MonitorRecoveryPolicy.ESCALATE
            else RecoveryKind.STALE_RUN_WATCHDOG
        )
        action_id = f"rec_{uuid.uuid4().hex[:12]}"
        ledger.recovery_actions.open(
            RecoveryAction(
                id=action_id,
                source_task_id=monitor.task_id,
                kind=kind,
                owner_employee_id=monitor.employee_id,
                cause="monitor_exhausted",
                fingerprint="monitor",
                next_action="resolve the stalled external dependency or hand it off",
            )
        )
        # Governance audit (spec 08 §5): an exhausted monitor surfaced a recovery.
        record_activity(
            ledger,
            verb=ActivityVerb.RECOVERED,
            subject_id=monitor.task_id,
            actor_employee_id=monitor.employee_id,
            payload={"cause": "monitor_exhausted", "recovery_action": action_id},
        )

    def _dispatch_beat(self, wake: Wake, *, run_id: str, now: datetime) -> None:
        """Kick a beat off as a background task — the tick never awaits it (spec 03 §3d).

        The handle is tracked so a composition root (or a test) can :meth:`drain` the inflight beats
        deterministically; the done-callback drops it so the set self-prunes.
        """
        task = asyncio.create_task(self.run_beat(wake, run_id=run_id, now=now))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)

    async def drain(self) -> None:
        """Await every beat this scheduler has dispatched — the tick's async tail (spec 03 §3d)."""
        if self._inflight:
            await asyncio.gather(*tuple(self._inflight))

    async def _run_beat_with_retry(
        self,
        beat_runner: BeatRunner,
        *,
        run_id: str,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...],
        observer: Callable[[Event], None] | None,
    ) -> BeatOutcome:
        """Run the beat, re-running a *transient* engine fault before stranding it (spec 05 §5).

        A retryable ``ERRORED`` outcome — a planner/evaluator parse blip, where the model emitted
        unparseable structured output — usually clears on a fresh attempt, so the beat is re-run up to
        ``transient_retries`` times. A clean return, a DoD failure, a cancel, or a hard (non-retryable)
        engine fault is returned as-is. Same ``run_id`` throughout: the retries are one beat.
        """
        attempt = 0
        while True:
            result = await beat_runner.run_task(
                run_id=run_id,
                task_id=task_id,
                intent=intent,
                verification=verification,
                observer=observer,
            )
            transient = result.disposition is BeatDisposition.ERRORED and result.retryable
            if not transient or attempt >= self.transient_retries:
                return result
            attempt += 1

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
        beat_runner_for = self._require(self._beat_runner_for, "beat_runner")

        task_id = str(wake.payload["task_id"])
        task = ledger.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        employee = workforce.get(wake.employee_id)

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

        # Mechanical integrate (M3 §5): a re-invocation whose delegated subtree is already complete is
        # landed by the kernel — NOT a model beat. Running a manager beat here would re-plan and let the
        # model call ``decompose`` again, ballooning the subtree and starving later work; the integrate
        # is mechanical by definition ("all children terminal"). Slice 2 replaces this with a real,
        # deliberately-scoped reacting integrate beat.
        if ledger.tasks.has_children(task_id) and ledger.tasks.all_children_terminal(task_id):
            verifier = ledger.dod.verifier_for_task(task_id)
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=None)
            await self._land_passed(
                task_id, run_id=run_id, verifier=verifier, verdict=None,
                employee=employee, result=BeatOutcome(passed=True, outcome={}, summary="integrated"),
            )
            ledger.tasks.release_locks(task_id, run_id=run_id)
            ledger.wakes.mark_done(wake.id)
            return

        observer = self._event_bus.emit if self._event_bus is not None else None
        verifier = None
        try:
            # Resolve the runner whose harness is materialized for *this* employee's role (spec 06 §2).
            beat_runner = beat_runner_for.runner_for(employee)
            # Intake DoD (spec 04 §1 / 06 §2): a task with no explicit DoD inherits its assignee role's, so
            # a beat is always held to the role's gate — the engineer to its tests, etc. A DoD a human set
            # via ``dod set`` always wins (only filled when absent). Persisted so ``task <id>`` shows it.
            if (
                self._roles is not None
                and employee.role in self._roles
                and ledger.dod.get_for_task(task_id) is None
            ):
                ledger.dod.create(task_id, self._roles.get(employee.role).dod_generator(task.intent))
            # The DoD's objective checks ride into the beat: dream's evaluator runs them as the
            # acceptance gate, so ``done`` means plan-complete *and* the Command gate passed (spec 04 §1).
            verifier = ledger.dod.verifier_for_task(task_id)
            verification = verifier.verification_steps() if verifier is not None else ()
            result = await self._run_beat_with_retry(
                beat_runner,
                run_id=run_id,
                task_id=task_id,
                intent=task.intent,
                verification=verification,
                observer=observer,
            )
        except Exception as exc:
            result = failure_outcome(exc)

        verdict = result.outcome or None
        if result.disposition is BeatDisposition.CANCELLED:
            # Cooperative cancel (caps/budget/operator): record a cancelled run and return the task
            # to its pre-beat (dispatchable) state — no DoD verdict, no recovery card (spec 05 §5/§6).
            ledger.runs.finish(run_id, RunStatus.CANCELLED, outcome=verdict)
            ledger.tasks.set_status(task_id, TaskStatus.TODO)
        elif ledger.tasks.has_children(task_id):
            # The task delegated: its lifecycle is its subtree's, not its own dream verdict (spec M3 §5).
            # This is the fifth beat outcome — the manager "succeeded by delegating".
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            if ledger.tasks.all_children_terminal(task_id):
                # INTEGRATE — Mechanical DoD: the whole subtree is terminal, so the parent is complete.
                await self._land_passed(
                    task_id, run_id=run_id, verifier=verifier, verdict=verdict,
                    employee=employee, result=result,
                )
            else:
                # PARK (delegated) — wait for the children; not done, not failed, no recovery ladder.
                ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
        elif result.disposition is BeatDisposition.ERRORED:
            # Engine/tool fault: the run failed and the task is stranded onto the recovery ladder with
            # the phase on the evidence, owner preserved — never collapsed into a DoD failure (§5).
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            self._strand_errored(task_id, employee_id=employee.id, result=result)
        elif result.passed:
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            await self._land_passed(
                task_id, run_id=run_id, verifier=verifier, verdict=verdict, employee=employee, result=result
            )
        else:
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            ledger.finalize_beat(
                task_id=task_id, run_id=run_id, dod_status=DodStatus.FAILED, verdict=verdict
            )
            self._climb_repair_ladder(task_id, employee_id=employee.id, verifier=verifier)

        await self._capture_memory(run_id=run_id, employee=employee, task=task, result=result, now=now)
        ledger.tasks.release_locks(task_id, run_id=run_id)
        ledger.wakes.mark_done(wake.id)
        self._record_cost(employee.id, task_id=task_id, run_id=run_id, result=result, now=now)

    async def _capture_memory(
        self, *, run_id: str, employee: Employee, task: Task, result: BeatOutcome, now: datetime
    ) -> None:
        """Write one raw episodic sprint delta for this beat (spec 07 §3) — the kernel stays writer-agnostic.

        A cancelled beat (nothing happened) records nothing; every other disposition leaves an honest
        trace whose fields are derived from the run, never authored by the worker.
        """
        if self._memory_writer is None or result.disposition is BeatDisposition.CANCELLED:
            return
        delta = _sprint_delta(
            run_id=run_id, employee=employee, task=task, result=result,
            scope=self._memory_scope(employee), now=now,
        )
        await self._memory_writer.apply(delta.to_memory_delta())

    def _memory_scope(self, employee: Employee) -> str:
        """The employee's write scope — its role's ``memory_scope`` (``project`` when unknown)."""
        if self._roles is not None and employee.role in self._roles:
            return self._roles.get(employee.role).manifest.memory_scope.value
        return "project"

    async def _land_passed(
        self,
        task_id: str,
        *,
        run_id: str,
        verifier: Verifier | None,
        verdict: dict[str, object] | None,
        employee: Employee,
        result: BeatOutcome,
    ) -> None:
        """A passed beat lands its role's outcome, then ``done`` — unless its DoD is a human sign-off.

        For a ``HumanApproval`` DoD the deliverable is produced but a person decides: open an
        **acceptance** gate (parks the task ``blocked`` pending the approval) instead of finalising
        (spec 04 §1 + §5). Otherwise the role's :class:`~chorus.outcomes.OutcomeLander` records the
        deliverable as a reviewable artifact (spec 04 §2) before the task is finalised ``done``.
        """
        ledger = self._require_ledger()
        if verifier is not None and verifier.kind is DoDKind.HUMAN_APPROVAL:
            GovernanceResolver(ledger).open_task_gate(
                task_id, gate_kind=ApprovalGate.ACCEPTANCE, reason=f"human-approval DoD for {task_id}"
            )
            return
        await self._land_outcome(task_id, employee=employee, result=result)
        ledger.finalize_beat(
            task_id=task_id, run_id=run_id, dod_status=DodStatus.PASSED, verdict=verdict
        )

    async def _land_outcome(self, task_id: str, *, employee: Employee, result: BeatOutcome) -> None:
        """Record the role's deliverable as an artifact via its registered lander (spec 04 §2).

        A no-op when no lander registry is wired or the employee's role lands no artifact kind — the
        beat still finalises ``done``, so landing is purely additive (the strict-completion record).
        """
        if self._landers is None or self._roles is None or employee.role not in self._roles:
            return
        outcome_kind = self._roles.get(employee.role).outcome_kind
        lander = self._landers.get(outcome_kind)
        if lander is None:
            return
        ledger = self._require_ledger()
        task = ledger.tasks.get(task_id)
        if task is None:
            return
        artifact = await lander.land(task, result)
        ledger.artifacts.create(_to_ledger_artifact(artifact))

    def _climb_repair_ladder(
        self, task_id: str, *, employee_id: str, verifier: Verifier | None
    ) -> None:
        """A failed beat climbs the bounded self-repair ladder, owning the task's status (spec 04 §1).

        Rung 1 (``Command`` DoD, budget left) — keep the task ``todo`` and re-wake the same assignee
        to retry: a live wake means the recovery sweep leaves it alone. Rung 3 (budget spent) — set
        ``blocked`` + a ``recovery_action`` for a human (no further retry). A non-Command failure has
        no objective gate to retry, so it goes straight to ``blocked``.
        """
        ledger = self._require_ledger()
        if verifier is None or verifier.kind is not DoDKind.COMMAND:
            ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            return
        failures = sum(1 for run in ledger.runs.for_task(task_id) if run.status is RunStatus.FAILED)
        if failures <= self.max_repair_attempts:
            ledger.tasks.set_status(task_id, TaskStatus.TODO)  # dispatchable; not yet "stuck"
            ledger.wakes.enqueue(
                Wake(
                    id=f"wake_{uuid.uuid4().hex[:12]}",
                    employee_id=employee_id,
                    reason=WakeReason.RECOVERY,
                    payload={"task_id": task_id, "cause": "dod_failed"},
                )
            )
            return
        ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
        if ledger.recovery_actions.active_for_source(task_id) is None:
            ledger.recovery_actions.open(
                RecoveryAction(
                    id=f"rec_{uuid.uuid4().hex[:12]}",
                    source_task_id=task_id,
                    kind=RecoveryKind.STALE_RUN_WATCHDOG,
                    owner_employee_id=employee_id,
                    cause="dod_repair_exhausted",
                    fingerprint="dod",
                    next_action="fix the failing check or revise the DoD",
                )
            )

    def _strand_errored(
        self, task_id: str, *, employee_id: str, result: BeatOutcome
    ) -> None:
        """An engine-faulted beat strands its task onto the recovery ladder (spec 05 §5, spec 02 §6).

        Distinct from a DoD failure: there is no objective gate to re-run, so the task goes ``blocked``
        and opens a first-class ``recovery_action`` (owner preserved) carrying the ``run_task`` phase +
        error as evidence, so the escalation trail names *where* the loop broke. At most one open
        stranded recovery per task — a re-strand under a live card is a no-op.
        """
        ledger = self._require_ledger()
        ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
        if ledger.recovery_actions.active_for_source(task_id) is not None:
            return
        phase = result.outcome.get("phase")
        ledger.recovery_actions.open(
            RecoveryAction(
                id=f"rec_{uuid.uuid4().hex[:12]}",
                source_task_id=task_id,
                kind=RecoveryKind.STRANDED,
                owner_employee_id=employee_id,
                cause="run_task_error",
                fingerprint=str(phase) if phase else "engine",
                evidence={"phase": phase, "error": result.outcome.get("error")},
                next_action="inspect the engine fault and resume or hand off the task",
            )
        )

    def _record_cost(
        self, employee_id: str, *, task_id: str, run_id: str, result: BeatOutcome, now: datetime
    ) -> None:
        """Record the beat's spend as a cost event and run Gate 2 against it (spec 04 §3).

        The cost event is the durable spend ledger (recorded whenever a beat cost something); Gate 2
        only fires when a budget enforcer is wired. A zero-cost beat is a no-op.
        """
        if result.cost_cents <= 0:
            return
        ledger = self._require_ledger()
        event = ledger.cost_events.record(
            CostEvent(
                id=f"cost_{uuid.uuid4().hex[:12]}",
                employee_id=employee_id,
                task_id=task_id,
                run_id=run_id,
                provider="dream",
                model=result.model,
                cost_cents=result.cost_cents,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                occurred_at=now,
            )
        )
        if self._budget_enforcer is not None:
            self._budget_enforcer.on_cost_event(event, now=now)

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
