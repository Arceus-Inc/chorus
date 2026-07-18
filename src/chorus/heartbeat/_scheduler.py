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
import json
import logging
import subprocess
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, runtime_checkable

from chorus.adapters._failure import failure_outcome
from chorus.cron._fire import fire_routine
from chorus.events import Event, EventKind
from chorus.governance import GovernanceResolver
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.heartbeat._beat_context import BeatContext, IntegrateContextPacket
from chorus.heartbeat._execution_profile import (
    ExecutionProfileResolver,
    ResolvedExecutionProfile,
)
from chorus.heartbeat._invokability import InvokabilityReason, invokability_block
from chorus.heartbeat._runner_for import single
from chorus.heartbeat._wake import TickReport, Wake
from chorus.ids import mint_id
from chorus.ledger import ApprovalGate, TaskPriority
from chorus.ledger._models import (
    ActivityVerb,
    Artifact,
    ArtifactType,
    CostEvent,
    DelegationContractStatus,
    DodStatus,
    ExecutionMode,
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
from chorus.lifecycle._team_policy import MissionTeamPolicy
from chorus.memory import EpisodicStore, SprintDelta, beat_fingerprint
from chorus.observability._trace import TraceStamper, trace_root
from chorus.outcomes import (
    AgentReview,
    DoDKind,
    ReviewedBuild,
    ReviewedBuildEvidenceProfile,
    Verifier,
)
from chorus.recovery import reconcile
from chorus.verification import SYSTEM_VERIFIER, VerificationPrincipal

if TYPE_CHECKING:
    from chorus.budgets import BudgetEnforcer
    from chorus.heartbeat._beat import BeatRunner
    from chorus.heartbeat._runner_for import BeatRunnerFor
    from chorus.ledger import Ledger, Task
    from chorus.observability import EventSink
    from chorus.outcomes import Artifact as OutcomeArtifact
    from chorus.outcomes import LanderRegistry, VerificationStep
    from chorus.roles import RoleRegistry
    from chorus.workforce import Employee, Workforce

_T = TypeVar("_T")
_logger = logging.getLogger("chorus.heartbeat.scheduler")
_MAX_EVIDENCE_BYTES = 1_048_576


def _read_evidence_object(
    worktree: Path, relative_path: str
) -> tuple[dict[str, object] | None, str]:
    """Load one bounded, regular JSON evidence object from the worktree."""
    path = worktree / relative_path
    if not path.is_file() or path.is_symlink():
        return None, f"{relative_path} is missing or is not a regular file"
    try:
        if path.stat().st_size > _MAX_EVIDENCE_BYTES:
            return None, f"{relative_path} exceeds {_MAX_EVIDENCE_BYTES} bytes"
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{relative_path} is not valid JSON: {exc}"
    if not isinstance(value, dict):
        return None, f"{relative_path} must contain a JSON object"
    return value, ""


def _tdd_review_evidence_passes(worktree: Path) -> tuple[bool, str]:
    """Validate the versioned RED, gate, plan, and independent-review evidence contract."""
    manifest, reason = _read_evidence_object(worktree, "test_evidence/manifest.json")
    if manifest is None:
        return False, reason
    gates = manifest.get("gates")
    if manifest.get("verdict") != "pass" or not isinstance(gates, list) or not gates:
        return False, "test_evidence/manifest.json must declare pass with at least one gate"
    for index, gate in enumerate(gates):
        if not isinstance(gate, dict):
            return False, f"test_evidence/manifest.json gate {index} is not an object"
        if (
            not str(gate.get("name", "")).strip()
            or not str(gate.get("command", "")).strip()
            or gate.get("status") != "pass"
            or type(gate.get("returncode")) is not int
            or gate.get("returncode") != 0
        ):
            return False, f"test_evidence/manifest.json gate {index} is not a recorded pass"

    red, reason = _read_evidence_object(worktree, "test_evidence/red.json")
    if red is None:
        return False, reason
    test_paths = red.get("test_paths")
    test_hashes = red.get("test_hashes")
    if (
        red.get("verdict") != "red-confirmed"
        or red.get("expected_failure_matched") is not True
        or red.get("command_unavailable") is not False
        or not str(red.get("command", "")).strip()
        or type(red.get("returncode")) is not int
        or red.get("returncode") == 0
        or not isinstance(test_paths, list)
        or not test_paths
        or not all(isinstance(path, str) and path.strip() for path in test_paths)
        or not isinstance(test_hashes, dict)
        or set(test_hashes) != set(test_paths)
        or not all(isinstance(value, str) and len(value) == 64 for value in test_hashes.values())
        or red.get("production_paths") != []
        or red.get("invalid_test_paths") != []
        or red.get("missing_tests") != []
    ):
        return False, "test_evidence/red.json does not prove valid RED-before-production"
    for relative_path in test_paths:
        candidate = Path(relative_path)
        if candidate.is_absolute() or ".." in candidate.parts:
            return False, f"test_evidence/red.json test path escapes worktree: {relative_path}"
        test_path = worktree / candidate
        if not test_path.is_file() or test_path.is_symlink():
            return False, f"RED-captured test is missing or invalid: {relative_path}"
        try:
            current_hash = sha256(test_path.read_bytes()).hexdigest()
        except OSError as exc:
            return False, f"RED-captured test cannot be read: {relative_path}: {exc}"
        if current_hash != test_hashes[relative_path]:
            return False, f"RED-captured test changed after RED: {relative_path}"

    test_plan, reason = _read_evidence_object(worktree, "test_plan.json")
    if test_plan is None:
        return False, reason
    if not test_plan:
        return False, "test_plan.json must contain a non-empty independent test plan"

    review, reason = _read_evidence_object(worktree, "review_verdict.json")
    if review is None:
        return False, reason
    findings = review.get("findings")
    if (
        review.get("cleared") is not True
        or not isinstance(findings, list)
        or not str(review.get("evidence", "")).strip()
        or any(
            isinstance(finding, dict) and finding.get("severity") == "high" for finding in findings
        )
    ):
        return False, "review_verdict.json is not a cleared independent review"
    return True, "structured TDD and review evidence passed"


@runtime_checkable
class _RunnerWithWorkingDir(Protocol):
    """A beat runner that exposes its worktree — where the kernel drops per-beat context files.

    Not every :class:`~chorus.heartbeat.BeatRunner` runs in a working dir (a fake/in-memory runner
    has none), so this is a narrow capability the kernel checks for before writing the integrate
    packet — typed, rather than a structural ``getattr`` probe.
    """

    @property
    def working_dir(self) -> Path | None: ...


@runtime_checkable
class _ReviewRunnerFor(Protocol):
    """A factory that can materialize a read-only reviewer beat at *another* employee's worktree.

    The reviewer inspects the work under review in place (the author's worktree), so the verdict is
    rendered on the real diff. Checked structurally so a plain :class:`BeatRunnerFor` (no review seam)
    degrades gracefully to materializing the reviewer in its own worktree.
    """

    def review_runner_for(
        self, reviewer: VerificationPrincipal, *, task_id: str, worktree_owner_id: str
    ) -> BeatRunner: ...


@runtime_checkable
class _VerificationRunnerFor(Protocol):
    """Materialize a reviewer that can inspect but cannot write a verdict or mutate work."""

    def verification_runner_for(
        self, reviewer: VerificationPrincipal, *, task_id: str, worktree_owner_id: str
    ) -> BeatRunner: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


# How much of a verify command's combined stdout+stderr the kernel keeps as durable evidence.
_VERIFY_OUTPUT_TAIL = 4000
# Exit codes the kernel synthesizes when the command never produces one of its own.
_VERIFY_TIMEOUT_EXIT = 124
_VERIFY_SPAWN_FAILED_EXIT = 127


def _run_verify_command(worktree: Path, command: str, *, timeout_s: int) -> tuple[int, str]:
    """Run a reviewer-discovered verify command in ``worktree`` — the kernel's objective floor.

    Returns ``(exit_code, output_tail)``. A timeout or a spawn failure is a *non-zero* exit (treated as a
    failing build), so a build can never pass by failing to run. Runs in the engineer's already-isolated,
    already-unrestricted worktree — the same trust tier the engineer itself executes at (M3 reviewed-build).
    """
    try:
        completed = subprocess.run(
            command,
            shell=True,
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        captured = _as_text(exc.stdout) + _as_text(exc.stderr)
        return _VERIFY_TIMEOUT_EXIT, f"timeout after {timeout_s}s\n{captured}"[
            -_VERIFY_OUTPUT_TAIL:
        ]
    except OSError as exc:
        return _VERIFY_SPAWN_FAILED_EXIT, f"failed to run {command!r}: {exc}"[-_VERIFY_OUTPUT_TAIL:]
    return completed.returncode, (completed.stdout + completed.stderr)[-_VERIFY_OUTPUT_TAIL:]


def _as_text(value: str | bytes | None) -> str:
    """Coerce subprocess output (which the stdlib types as ``str | bytes | None``) to text."""
    if value is None:
        return ""
    return value if isinstance(value, str) else value.decode("utf-8", "replace")


_MANIFEST_MAX_FILES = 200
# Top-level dirs that are infrastructure, not the author's deliverable: git plumbing and the kernel's
# own per-beat harness injection (role overlays, sandbox config, cron). A diff review never inspects
# these — they are identical in every worktree — so they are excluded to keep the manifest signal-rich.
_MANIFEST_EXCLUDED_ROOTS = frozenset({".git", ".dream", ".harness"})


def _worktree_file_manifest(worktree: Path | None, *, max_files: int = _MANIFEST_MAX_FILES) -> str:
    """The relative paths of the author's files in ``worktree`` — what a list-less reviewer can't see.

    A read-only Reviewer's toolset is ``(read_file, submit_verdict)``: it can read a file by path but has
    no way to enumerate a directory. Without this it guesses standard manifest names, misses the author's
    actual files, and wrongly judges the worktree empty. The kernel hands it the listing so it reviews
    what is really there. Harness/VCS plumbing (:data:`_MANIFEST_EXCLUDED_ROOTS`) is dropped; the list is
    sorted and capped.
    """
    if worktree is None or not worktree.is_dir():
        return ""
    paths: list[str] = []
    for path in sorted(worktree.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(worktree)
        if rel.parts and rel.parts[0] in _MANIFEST_EXCLUDED_ROOTS:
            continue
        paths.append(rel.as_posix())
        if len(paths) >= max_files:
            paths.append(f"… (listing truncated at {max_files} files)")
            break
    return "\n".join(paths)


# Leaf DoD kinds the kernel still gates with a separate read-only Reviewer beat. Spec 16 collapses
# ``agent_review`` into dream's single in-beat evaluator (its rubric rides into ``run_task``), so only
# ``reviewed_build`` keeps a second beat — for its reviewer-discovered objective command floor.
_REVIEWER_GATED_DODS = frozenset({DoDKind.REVIEWED_BUILD})


def _review_rubric(spec: object) -> str:
    """The rubric carried by a reviewer-gated DoD."""
    if isinstance(spec, AgentReview | ReviewedBuild):
        return spec.rubric
    return ""


_OUTCOME_BY_DISPOSITION: dict[BeatDisposition, str] = {
    BeatDisposition.PASSED: "done",
    BeatDisposition.DOD_FAILED: "needs_changes",
    BeatDisposition.ERRORED: "blocked",
}


def _episodic_outcome(result: BeatOutcome) -> str:
    """Human label for the episodic record — timeouts are unfinished, not stranded.

    Wall-clock ``TimeoutError`` burns a resume slot and the worktree + TODO.md survive, so stamping
    those records ``blocked`` misleads ``recall`` into treating mid-build progress as a strand. Map
    timeout faults to ``incomplete`` so the next beat continues from listed files instead of restarting.
    """
    if result.disposition is BeatDisposition.ERRORED:
        err = str((result.outcome or {}).get("error", ""))
        if "TimeoutError" in err:
            return "incomplete"
    return _OUTCOME_BY_DISPOSITION.get(result.disposition or BeatDisposition.ERRORED, "blocked")


def _artifact_ref(artifact: Artifact) -> str:
    """A stable string reference for the episodic record — the artifact's id-like fields, not its dict.

    Prefers the string identifiers (``external_id``/``url``); falls back to a canonical JSON dump of the
    structured ``resource_ref`` (e.g. an engineer PR's branch+commit) so the record stays ``str``-typed.
    """
    if artifact.external_id:
        return artifact.external_id
    if artifact.url:
        return artifact.url
    if artifact.resource_ref:
        return json.dumps(artifact.resource_ref, sort_keys=True, default=str)
    return ""


def _baseline_sha(working_dir: Path | None) -> str | None:
    """The worktree HEAD at beat-start — the fingerprint baseline. ``None`` when unavailable.

    Captured at dispatch (before the lander commits) so the fingerprint diff at beat-end spans exactly
    this beat's work. Best-effort: a runner with no worktree, or a dir that is not a git repo, yields
    no baseline rather than raising.
    """
    if working_dir is None:
        return None
    try:
        head = subprocess.run(
            ["git", "-C", str(working_dir), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        return None
    return head or None


def _execution_intent(ledger: Ledger, task: Task) -> str:
    """Carry ancestor objectives into a delegated beat without widening its assigned scope."""
    if task.parent_id is None:
        return task.intent

    ancestors: list[Task] = []
    parent_id: str | None = task.parent_id
    visited = {task.id}
    while parent_id is not None and parent_id not in visited:
        visited.add(parent_id)
        parent = ledger.tasks.get(parent_id)
        if parent is None:
            break
        ancestors.append(parent)
        parent_id = parent.parent_id

    if not ancestors:
        return task.intent
    context = "\n".join(f"- {ancestor.id}: {ancestor.intent}" for ancestor in reversed(ancestors))
    return (
        f"{task.intent}\n\n"
        "Parent objective context (preserve its acceptance criteria):\n"
        f"{context}\n\n"
        "Do not expand beyond the assigned child scope. Use this context only to keep the child "
        "contract faithful to the delegated objective."
    )


def _sprint_delta(
    *,
    run_id: str,
    employee: Employee,
    task: Task,
    result: BeatOutcome,
    scope: str,
    now: datetime,
    files_touched: tuple[str, ...] = (),
    artifacts: tuple[str, ...] = (),
) -> SprintDelta:
    """Build the beat's raw episodic record — honest fields derived from the run (spec 07 §3)."""
    verdict = result.outcome or {}
    raw_score = verdict.get("score")
    score = (
        float(raw_score) if isinstance(raw_score, int | float) else (1.0 if result.passed else 0.0)
    )
    return SprintDelta(
        run_id=run_id,
        task_id=task.id,
        employee_id=employee.id,
        scope=scope,
        intent=task.intent,
        outcome=_episodic_outcome(result),
        score=score,
        created_at=now,
        role=employee.role,
        recorded_at=now,
        files_touched=files_touched,
        artifacts=artifacts,
        body=result.raw_record or result.summary or "",
    )


def _to_ledger_artifact(artifact: OutcomeArtifact) -> Artifact:
    """Map a lander's canonical :class:`~chorus.outcomes.Artifact` to a storable ledger row."""
    return Artifact(
        id=mint_id(),
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
        max_resume_attempts: int = 2,
        transient_retries: int = 2,
        max_integrate_iterations: int = 3,
        max_review_rounds: int = 2,
        memory_writer: EpisodicStore | None = None,
        company_root: Path | None = None,
        ledger: Ledger | None = None,
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
        self.max_repair_attempts = (
            max_repair_attempts  # DoD-failure self-repair budget (spec 04 §1)
        )
        # Budget-exhaustion RESUME budget: how many times a timed-out beat re-dispatches to continue
        # from its worktree + TODO.md before the task strands as too-big-for-one-beat. Distinct from the
        # DoD repair budget — a timeout is unfinished work, not a rejected attempt.
        self.max_resume_attempts = max_resume_attempts
        # In-beat retry budget for *transient* engine faults (a planner/evaluator parse blip): re-run the
        # beat this many times before stranding it onto the recovery ladder (spec 05 §5).
        self.transient_retries = transient_retries
        # How many adaptive integrate beats a manager gets per goal before the kernel forces
        # acceptance of the completed subtree — bounds the submit→re-integrate loop (spec M3 §5).
        self.max_integrate_iterations = max_integrate_iterations
        # How many times a reviewer may block a standalone (no-manager) deliverable and have its author
        # self-repair before the kernel opens a recovery card for a human (M3 load-bearing Reviewer).
        self.max_review_rounds = max_review_rounds
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
        self._landers = (
            landers  # None = a passed beat lands 'done' without recording a role artifact
        )
        self._memory_writer = (
            memory_writer  # None = no episodic capture (the kernel is writer-agnostic)
        )
        self._company_root = company_root  # None = no lattice beat-end gate (lattice is optional)
        self._clock = clock or _utc_now  # the time source the run loop stamps each pulse with
        self._sleep = (
            sleep or asyncio.sleep
        )  # the inter-pulse wait (injectable for deterministic tests)
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
        for (
            reaped_run_id
        ) in swept.reaped_runs:  # watchdog: a reaped lease is a red lane, not a counter
            reaped = ledger.runs.get(reaped_run_id)
            if reaped is not None:
                self._emit_allocation(
                    EventKind.RUN_STALLED,
                    at=now,
                    task_id=reaped.task_id,
                    employee_id=reaped.employee_id,
                    run_id=reaped.id,
                    payload={"reason": "lease_expired"},
                )
        recovered = len(swept.reaped_runs) + self._recover_landed_delegations(ledger)

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
                    id=mint_id(),
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
            # Exception: a parent whose subtree is wholly terminal integrates *now*, even if a child was
            # ``rejected`` (a reviewer block) rather than ``done`` — so the manager reacts to the rejection
            # instead of parking forever on an unresolvable gate (M3 load-bearing Reviewer).
            gate_task_id = str(wake.payload["task_id"])
            ready_to_integrate = ledger.tasks.has_children(
                gate_task_id
            ) and ledger.tasks.all_children_terminal(gate_task_id)
            if ledger.dependencies.unresolved_blockers(gate_task_id) and not ready_to_integrate:
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
            employee = ledger.employees.get(wake.employee_id)
            if (
                employee is not None
                and employee.role == "manager"
                and ledger.management_profiles.get(employee.id) is None
            ):
                reason = InvokabilityReason.UNMIGRATED_MANAGER
                task_id = str(wake.payload["task_id"])
                _logger.warning(
                    "refusing dispatch for unmigrated Manager %s; run workforce "
                    "specialize-manager before retrying",
                    employee.id,
                )
                ledger.wakes.mark_done(wake.id)
                ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
                if ledger.recovery_actions.active_for_source(task_id) is None:
                    ledger.recovery_actions.open(
                        RecoveryAction(
                            id=mint_id(),
                            source_task_id=task_id,
                            kind=RecoveryKind.STRANDED,
                            owner_user_id="operator",
                            cause=reason.value,
                            fingerprint=employee.id,
                            evidence={"employee_id": employee.id, "role": employee.role},
                            next_action=(
                                "run workforce specialize-manager with an explicit profession "
                                "and management profile"
                            ),
                        )
                    )
                invokability_skipped += 1
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
                self._emit_allocation(
                    EventKind.BUDGET_HARD_STOP,
                    at=now,
                    task_id=str(wake.payload["task_id"]),
                    employee_id=wake.employee_id,
                    payload={"gate": "dispatch"},
                )
                continue
            task_id = str(wake.payload["task_id"])
            run_id = mint_id()
            # Dispatch CAS (spec 03 §5): checkout flips the task to ``in_progress`` under ``run_id``.
            # A False is a 409 — a live owner already holds it — so we release the wake and skip.
            if not ledger.tasks.checkout(task_id, employee_id=wake.employee_id, run_id=run_id):
                ledger.wakes.release(wake.id)
                continue
            busy.add(wake.employee_id)
            self._emit_allocation(
                EventKind.WAKE_CLAIMED,
                at=now,
                task_id=task_id,
                employee_id=wake.employee_id,
                run_id=run_id,
                payload={"reason": wake.reason.value, "coalesced": wake.coalesced_count},
            )
            self._emit_allocation(
                EventKind.TASK_STATUS,
                at=now,
                task_id=task_id,
                employee_id=wake.employee_id,
                run_id=run_id,
                payload={"from": "todo", "to": "in_progress"},
            )
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

    def _apply_monitor_recovery(self, ledger: Ledger, monitor: Monitor) -> None:
        """An exhausted monitor escalates per its recovery policy (spec 03 §3c, spec 01 Cluster B).

        ``wake_owner`` enqueues a recovery wake to the assignee; ``create_recovery``/``escalate``
        open a first-class ``recovery_action`` (at most one open per source task) — liveness stays
        visible rather than silently lapsing when the deferred check gives up.
        """
        if monitor.recovery_policy is MonitorRecoveryPolicy.WAKE_OWNER:
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
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
        action_id = mint_id()
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
        rubric: str,
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
                rubric=rubric,
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

        if task.execution_mode is ExecutionMode.DELEGATION and ledger.tasks.all_children_terminal(
            task.id
        ):
            contract = ledger.delegation_contracts.active_for_task(task.id)
            if contract is not None and contract.status is DelegationContractStatus.DELEGATED:
                ledger.delegation_contracts.update_status(
                    task.id, DelegationContractStatus.INTEGRATING
                )

        execution_profile: ResolvedExecutionProfile | None = None
        profile_error: Exception | None = None
        if self._roles is not None and employee.role in self._roles:
            try:
                execution_profile = ExecutionProfileResolver(self._roles, ledger).resolve(
                    employee, task
                )
            except Exception as exc:
                profile_error = exc

        # begin_execution — mint the run row the checkout lock already points at, with a fresh lease.
        # The lease TTL is the assignee role's (a research-heavy role widens it past the org default),
        # so a beat that blocks for minutes inside one uninterrupted subagent call isn't reaped.
        lease = now + timedelta(
            seconds=self._lease_seconds_for(employee, execution_profile=execution_profile)
        )
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

        # Integrate-iteration cap (M3 §5): a manager that keeps spawning follow-ups would re-park /
        # re-integrate forever, bounded only by budget. Past the cap, accept the completed subtree
        # mechanically — no further adaptive beat — so the loop is bounded.
        if profile_error is None and await self._maybe_cap_integrate(
            ledger,
            wake=wake,
            run_id=run_id,
            task=task,
            employee=employee,
            execution_profile=execution_profile,
            now=now,
        ):
            return

        trace_id = trace_root(ledger, task.id)  # the lineage root — the product's run anchor
        observer = (
            TraceStamper(
                self._event_bus.emit,
                trace_id=trace_id,
                task_id=task.id,
                employee_id=employee.id,
                run_id=run_id,
            )
            if self._event_bus is not None
            else None
        )
        verifier = None
        beat_runner: BeatRunner | None = None
        # The fingerprint baseline: HEAD *before* the beat runs, so the beat-end diff spans exactly this
        # beat's work (the lander commits between here and _capture_memory). None for a runner with no
        # worktree — a read-only beat leaves no fingerprint.
        working_dir: Path | None = None
        base_sha: str | None = None
        try:
            if profile_error is not None:
                raise profile_error
            # Resolve the runner for *this* employee's role + beat phase (an integrate beat — the task
            # already has children — is materialized without ``decompose``, spec 06 §2 / M3 §5).
            beat_runner = beat_runner_for.runner_for(employee, task_id=task_id)
            working_dir = (
                beat_runner.working_dir if isinstance(beat_runner, _RunnerWithWorkingDir) else None
            )
            base_sha = _baseline_sha(working_dir)
            if ledger.tasks.has_children(task_id) and ledger.tasks.all_children_terminal(task_id):
                self._write_integrate_packet(ledger, beat_runner=beat_runner, task_id=task_id)
            # Intake DoD (spec 04 §1 / 06 §2): a task with no explicit DoD inherits its assignee role's, so
            # a beat is always held to the role's gate — the engineer to its tests, etc. A DoD a human set
            # via ``dod set`` always wins (only filled when absent). Persisted so ``task <id>`` shows it.
            if execution_profile is not None and ledger.dod.get_for_task(task_id) is None:
                ledger.dod.create(task_id, execution_profile.verifier)
            # The DoD's objective checks ride into the beat: dream's evaluator runs them as the
            # acceptance gate, so ``done`` means plan-complete *and* the Command gate passed (spec 04 §1).
            verifier = ledger.dod.verifier_for_task(task_id)
            verification = verifier.verification_steps() if verifier is not None else ()
            # Spec 16: an ``agent_review`` DoD's rubric rides into dream's single in-beat evaluator so
            # one ``run_task`` renders the judgment verdict — no redundant second Reviewer beat. A
            # ``reviewed_build`` rubric is withheld here; its Reviewer beat still discovers + runs the
            # objective command floor (and would judge a worktree the in-beat evaluator can't yet see).
            rubric = (
                verifier.rubric()
                if verifier is not None and verifier.kind is DoDKind.AGENT_REVIEW
                else ""
            )
            result = await self._run_beat_with_retry(
                beat_runner,
                run_id=run_id,
                task_id=task_id,
                intent=_execution_intent(ledger, task),
                verification=verification,
                rubric=rubric,
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
        elif profile_error is not None:
            # Authority refused the beat BEFORE it ran (ExecutionProfileDenied — a revoked grant,
            # a contract/Team mismatch, a resolver fault). Even for a parent with children this is
            # never "success by delegating": recording SUCCEEDED here would walk the denial straight
            # into lead acceptance. Fail the run and strand it so an operator sees the denial.
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            self._resume_or_strand(task_id, employee_id=employee.id, result=result)
        elif ledger.tasks.has_children(task_id):
            # The task delegated: its lifecycle is its subtree's, not its own dream verdict (spec M3 §5).
            # This is the fifth beat outcome — the manager "succeeded by delegating".
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            if not ledger.tasks.all_children_terminal(task_id):
                # PARK (delegated) — wait for the children; not done, not failed, no recovery ladder.
                ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            elif task.execution_mode is ExecutionMode.DELEGATION:
                await self._finish_delegation_parent(
                    task=task,
                    run_id=run_id,
                    verifier=verifier,
                    verdict=verdict,
                    employee=employee,
                    result=result,
                    beat_runner=beat_runner,
                    outcome_kind=(
                        execution_profile.outcome_kind if execution_profile is not None else None
                    ),
                    now=now,
                )
            elif (
                self._integrate_floor_verdict(task_id, verifier=verifier, beat_runner=beat_runner)
                is False
            ):
                # ROLLUP GATE (run-18 false-`done` fix): the subtree is terminal, but the parent's
                # OBJECTIVE rollup DoD — a ``command`` floor, e.g. "every required deliverable exists and
                # the gate passes" — FAILED against the assembled company main. A delegated parent must
                # NOT mechanically claim ``done`` on a goal its own objective gate rejects: record the
                # failed verdict and park BLOCKED so the gap (a missing module / a dropped area) surfaces
                # honestly instead of being laundered into a false ``done``.
                ledger.finalize_beat(
                    task_id=task_id, run_id=run_id, dod_status=DodStatus.FAILED, verdict=verdict
                )
                ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            else:
                # INTEGRATE — the whole subtree is terminal and the parent's objective floor passed (or
                # it declares none), so the parent is complete (spec M3 §5).
                await self._land_passed(
                    task_id,
                    run_id=run_id,
                    verifier=verifier,
                    verdict=verdict,
                    employee=employee,
                    result=result,
                    outcome_kind=(
                        execution_profile.outcome_kind if execution_profile is not None else None
                    ),
                    now=now,
                )
        elif result.disposition is BeatDisposition.ERRORED:
            # Engine/tool fault: the run failed. A wall-clock TIMEOUT is unfinished-not-wrong — resume it
            # (re-dispatch from the persistent worktree + TODO.md, bounded); any other fault strands onto
            # the recovery ladder with the phase on the evidence, owner preserved (§5).
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            self._resume_or_strand(task_id, employee_id=employee.id, result=result)
        elif result.passed and task.execution_mode is ExecutionMode.DELEGATION:
            # A delegation root that never fanned out cannot be done — its lifecycle is its
            # subtree's, and the contract's acceptance/verification path only runs over children.
            # (Found live 2026-07-18: a kickoff beat "passed" its in-beat evaluation without
            # decomposing and landed DONE through the delivery path — zero children, contract
            # never verified.) Park it and re-wake the lead to decompose.
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
                    employee_id=employee.id,
                    reason=WakeReason.CHILDREN_DONE,
                    payload={"task_id": task_id, "cause": "delegation_root_never_decomposed"},
                )
            )
        elif result.passed:
            ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=verdict)
            await self._land_passed(
                task_id,
                run_id=run_id,
                verifier=verifier,
                verdict=verdict,
                employee=employee,
                result=result,
                outcome_kind=(
                    execution_profile.outcome_kind if execution_profile is not None else None
                ),
                now=now,
            )
        else:
            ledger.runs.finish(run_id, RunStatus.FAILED, outcome=verdict)
            ledger.finalize_beat(
                task_id=task_id, run_id=run_id, dod_status=DodStatus.FAILED, verdict=verdict
            )
            # A DoD failure on a *manager-parented* leaf escalates to the manager (mark REJECTED, wake it
            # on children_done) so its integrate beat reacts — the same coherence loop a reviewer block
            # drove (spec 15). Since spec 16 renders the ``agent_review`` verdict in-beat (no second
            # Reviewer beat), the child block now arrives here, not via ``_run_review`` → ``_route_block``;
            # routing it the same way keeps the manager loop intact. A standalone leaf climbs the bounded
            # self-repair ladder (spec 04 §1) as before.
            if self._manager_of(task) is not None:
                self._route_block(task_id, author=employee)
            else:
                self._climb_repair_ladder(task_id, employee_id=employee.id, verifier=verifier)

        await self._capture_memory(
            ledger,
            run_id=run_id,
            employee=employee,
            task=task,
            result=result,
            memory_scope=(
                execution_profile.config.memory_scope
                if execution_profile is not None
                else self._memory_scope(employee)
            ),
            now=now,
            working_dir=working_dir,
            base_sha=base_sha,
        )
        self._write_lattice_beat_end(
            employee=employee,
            run_id=run_id,
            working_dir=working_dir,
        )
        ledger.tasks.release_locks(task_id, run_id=run_id)
        ledger.wakes.mark_done(wake.id)
        self._record_cost(
            employee.id,
            task_id=task_id,
            run_id=run_id,
            trace_id=trace_id,
            result=result,
            now=now,
        )

    async def _capture_memory(
        self,
        ledger: Ledger,
        *,
        run_id: str,
        employee: Employee,
        task: Task,
        result: BeatOutcome,
        memory_scope: str | None = None,
        now: datetime,
        working_dir: Path | None,
        base_sha: str | None,
    ) -> None:
        """Write one raw episodic sprint delta for this beat (spec 07 §3) — the kernel stays writer-agnostic.

        A cancelled beat (nothing happened) records nothing; every other disposition leaves an honest
        trace whose fields — the structural fingerprint (``files_touched``) and the landed
        ``artifacts`` — are derived from the run, never authored by the worker.
        """
        if self._memory_writer is None or result.disposition is BeatDisposition.CANCELLED:
            return
        files_touched = beat_fingerprint(working_dir, base_sha)
        artifacts = tuple(
            ref
            for artifact in ledger.artifacts.list_for_task(task.id)
            if (ref := _artifact_ref(artifact))
        )
        delta = _sprint_delta(
            run_id=run_id,
            employee=employee,
            task=task,
            result=result,
            scope=memory_scope or self._memory_scope(employee),
            now=now,
            files_touched=files_touched,
            artifacts=artifacts,
        )
        self._memory_writer.append(delta)

    def _write_lattice_beat_end(
        self,
        *,
        employee: Employee,
        run_id: str,
        working_dir: Path | None,
    ) -> None:
        """Post-beat lattice teaser file — gate-gated, non-blocking (integration-plan §4.4)."""
        if self._company_root is None or working_dir is None:
            return
        harness = working_dir / ".harness"
        path = harness / "lattice-beat-end.json"
        try:
            from chorus_tools._lattice_bridge import build_lattice_for_chorus

            lattice = build_lattice_for_chorus(self._company_root)
            if not lattice.gate_open(employee.id):
                if path.exists():
                    path.unlink()
                return
            payload = {
                "gate_open": True,
                "teaser": lattice.beat_end_teaser(employee.id),
                "employee_id": employee.id,
                "run_id": run_id,
            }
            harness.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            from chorus_tools._lattice_bridge import write_lattice_error

            write_lattice_error(working_dir, site="scheduler.beat_end_gate", error=exc)
            return

    def _write_integrate_packet(
        self, ledger: Ledger, *, beat_runner: BeatRunner, task_id: str
    ) -> None:
        """Write the manager's child-feedback packet when the runner exposes a working directory."""
        if not isinstance(beat_runner, _RunnerWithWorkingDir):
            return
        working_dir = beat_runner.working_dir
        if working_dir is None:
            return
        IntegrateContextPacket.build(ledger, parent_task_id=task_id).write(working_dir)

    def _integrate_floor_verdict(
        self, task_id: str, *, verifier: Verifier | None, beat_runner: BeatRunner | None
    ) -> bool | None:
        """Run the parent's objective ``command`` floor against the integrator's worktree at rollup.

        Spec M3 §5 lands a delegated parent ``done`` the instant its subtree is terminal — a *mechanical*
        rollup that never asks whether the assembled result actually satisfies the goal. When the goal
        carries an objective ``command`` DoD (e.g. "every required deliverable exists and ``gate_check``
        passes"), that command IS the structural rollup gate: run it here, in the integrator's worktree
        (= company main once the children merged), and return whether every step exits 0.

        Returns ``None`` when there is no objective floor to run — no ``command`` DoD, or a seam that
        exposes no worktree (e.g. an in-memory test runner) — so the caller keeps the mechanical
        ``done`` acceptance unchanged. Returns ``True``/``False`` only when a real floor actually ran.
        """
        if verifier is None:
            return None
        steps = verifier.verification_steps()
        if not steps:
            return None
        worktree = (
            beat_runner.working_dir if isinstance(beat_runner, _RunnerWithWorkingDir) else None
        )
        if worktree is None:
            return None
        for step in steps:
            exit_code, _ = _run_verify_command(worktree, step.command, timeout_s=step.timeout_s)
            if exit_code != 0:
                return False
        return True

    async def _finish_delegation_parent(
        self,
        *,
        task: Task,
        run_id: str,
        verifier: Verifier | None,
        verdict: dict[str, object] | None,
        employee: Employee,
        result: BeatOutcome,
        beat_runner: BeatRunner | None,
        outcome_kind: str | None,
        now: datetime,
    ) -> None:
        """Require lead acceptance and an independent gate before closing delegated work."""
        ledger = self._require_ledger()
        contract = ledger.delegation_contracts.active_for_task(task.id)
        if contract is None:
            raise RuntimeError(f"delegation task {task.id!r} has no active contract")
        if not self._required_descendants_passed(task.id):
            ledger.tasks.set_status(task.id, TaskStatus.BLOCKED)
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
                    employee_id=employee.id,
                    reason=WakeReason.CHILDREN_DONE,
                    payload={"task_id": task.id, "cause": "required_descendant_failed"},
                )
            )
            return
        with ledger.transaction():
            ledger.delegation_contracts.accept_for_verification(task.id, run_id)
            record_activity(
                ledger,
                verb=ActivityVerb.LEAD_ACCEPTED,
                subject_kind="delegation_contract",
                subject_id=task.id,
                actor_employee_id=employee.id,
                payload={"run_id": run_id},
            )

        floor_passed = self._integrate_floor_verdict(
            task.id,
            verifier=verifier,
            beat_runner=beat_runner,
        )
        review_passed, reviewer_id, verification_run_id = await self._verify_delegation_parent(
            task=task,
            lead=employee,
            verifier=verifier,
            now=now,
        )
        verified = result.passed and review_passed and floor_passed is not False
        if not verified:
            with ledger.transaction():
                ledger.delegation_contracts.update_status(
                    task.id, DelegationContractStatus.INTEGRATING
                )
                record_activity(
                    ledger,
                    verb=ActivityVerb.PARENT_VERIFIED,
                    subject_kind="delegation_contract",
                    subject_id=task.id,
                    payload={
                        "passed": False,
                        "run_id": run_id,
                        "reviewer_id": reviewer_id,
                        "verification_run_id": verification_run_id,
                    },
                )
                ledger.finalize_beat(
                    task_id=task.id,
                    run_id=run_id,
                    dod_status=DodStatus.FAILED,
                    verdict=verdict,
                )
                ledger.tasks.set_status(task.id, TaskStatus.BLOCKED)
                ledger.wakes.enqueue(
                    Wake(
                        id=mint_id(),
                        employee_id=employee.id,
                        reason=WakeReason.CHILDREN_DONE,
                        payload={"task_id": task.id},
                    )
                )
            return

        await self._land_passed(
            task.id,
            run_id=run_id,
            verifier=verifier,
            verdict=verdict,
            employee=employee,
            result=result,
            outcome_kind=outcome_kind,
            now=now,
        )
        self._close_verified_delegation(
            task.id,
            run_id=run_id,
            recovered=False,
            reviewer_id=reviewer_id,
            verification_run_id=verification_run_id,
        )

    def _required_descendants_passed(self, task_id: str) -> bool:
        """Require every persisted parent gate, or every legacy direct child, to be done."""
        ledger = self._require_ledger()
        required_ids = ledger.dependencies.blockers(task_id)
        required = (
            [ledger.tasks.get(child_id) for child_id in required_ids]
            if required_ids
            else list(ledger.tasks.children(task_id))
        )
        return bool(required) and all(
            child is not None and child.status is TaskStatus.DONE for child in required
        )

    async def _verify_delegation_parent(
        self,
        *,
        task: Task,
        lead: Employee,
        verifier: Verifier | None,
        now: datetime,
    ) -> tuple[bool, str | None, str | None]:
        """Run the integrated parent gate under the non-workforce system verifier."""
        ledger = self._require_ledger()
        reviewer = SYSTEM_VERIFIER
        verification_run_id = mint_id()
        runner = self._verification_runner(
            reviewer,
            task_id=task.id,
            worktree_owner_id=lead.id,
        )
        ledger.runs.create(
            Run(
                id=verification_run_id,
                employee_id=lead.id,
                task_id=task.id,
                principal_kind="system",
                system_principal_id=reviewer.id,
                status=RunStatus.RUNNING,
                lease_expires_at=now + timedelta(seconds=self.lease_ttl_s),
                started_at=now,
            )
        )
        worktree = runner.working_dir if isinstance(runner, _RunnerWithWorkingDir) else None
        if worktree is not None:
            BeatContext(
                task_id=task.id,
                run_id=verification_run_id,
                employee_id=reviewer.id,
            ).write(worktree)
        rubric = verifier.rubric() if verifier is not None else task.intent
        try:
            review = await runner.run_task(
                task_id=task.id,
                run_id=verification_run_id,
                intent=(
                    f"Independently verify the integrated delegated objective: {task.intent}\n"
                    f"Objective rubric: {rubric}\n"
                    "Inspect the assembled result read-only and return a passing outcome only when "
                    "the objective is satisfied."
                ),
                rubric=rubric,
                observer=(
                    TraceStamper(
                        self._event_bus.emit,
                        trace_id=trace_root(ledger, task.id),
                        task_id=task.id,
                        employee_id=lead.id,
                        run_id=verification_run_id,
                    )
                    if self._event_bus is not None
                    else None
                ),
            )
        except Exception as exc:
            review = failure_outcome(exc)
        ledger.runs.finish(
            verification_run_id,
            RunStatus.SUCCEEDED if review.passed else RunStatus.FAILED,
            outcome=review.outcome or None,
        )
        return review.passed, reviewer.id, verification_run_id

    def _recover_landed_delegations(self, ledger: Ledger) -> int:
        """Close delegation metadata left behind after a verified parent landed."""
        recovered = 0
        for contract in ledger.delegation_contracts.landed_awaiting_closure():
            if contract.accepted_run_id is None:
                continue
            if self._close_verified_delegation(
                contract.task_id,
                run_id=contract.accepted_run_id,
                recovered=True,
            ):
                recovered += 1
        return recovered

    def _close_verified_delegation(
        self,
        task_id: str,
        *,
        run_id: str,
        recovered: bool,
        reviewer_id: str | None = None,
        verification_run_id: str | None = None,
    ) -> bool:
        """Atomically record verification, close the contract, and archive its Team."""
        ledger = self._require_ledger()
        with ledger.transaction():
            contract = ledger.delegation_contracts.get(task_id)
            if contract is None or contract.status is DelegationContractStatus.DONE:
                return False
            if contract.status is not DelegationContractStatus.VERIFYING:
                raise RuntimeError(
                    f"delegation task {task_id!r} cannot close from {contract.status.value!r}"
                )
            record_activity(
                ledger,
                verb=ActivityVerb.PARENT_VERIFIED,
                subject_kind="delegation_contract",
                subject_id=task_id,
                payload={
                    "passed": True,
                    "run_id": run_id,
                    **({"reviewer_id": reviewer_id} if reviewer_id is not None else {}),
                    **(
                        {"verification_run_id": verification_run_id}
                        if verification_run_id is not None
                        else {}
                    ),
                    **({"recovered": True} if recovered else {}),
                },
            )
            ledger.delegation_contracts.update_status(task_id, DelegationContractStatus.DONE)
            MissionTeamPolicy(ledger).archive(contract.team_id)
            if recovered:
                ledger.tasks.release_locks(task_id, run_id=run_id)
                run = ledger.runs.get(run_id)
                if run is not None and run.wake_id is not None:
                    ledger.wakes.mark_done(run.wake_id)
        return True

    async def _maybe_cap_integrate(
        self,
        ledger: Ledger,
        *,
        wake: Wake,
        run_id: str,
        task: Task,
        employee: Employee,
        execution_profile: ResolvedExecutionProfile | None,
        now: datetime,
    ) -> bool:
        """At the integrate-iteration cap, accept the completed subtree mechanically — no model beat.

        Returns ``True`` when it handled (and landed) the beat, so ``run_beat`` returns early. Only a
        re-invocation whose subtree is already complete can be capped; a kickoff or engineer beat
        (no terminal subtree) always returns ``False``.
        """
        if not (ledger.tasks.has_children(task.id) and ledger.tasks.all_children_terminal(task.id)):
            return False
        iteration = IntegrateContextPacket.iteration_for(ledger, task.id)
        if iteration <= self.max_integrate_iterations:
            return False
        if task.execution_mode is ExecutionMode.DELEGATION:
            evidence: dict[str, object] = {
                "iteration": iteration,
                "cap": self.max_integrate_iterations,
                "contract_task_id": task.id,
            }
            with ledger.transaction():
                ledger.runs.finish(run_id, RunStatus.FAILED, outcome=evidence)
                ledger.tasks.set_status(task.id, TaskStatus.BLOCKED)
                ledger.delegation_contracts.update_status(task.id, DelegationContractStatus.BLOCKED)
                if ledger.recovery_actions.active_for_source(task.id) is None:
                    ledger.recovery_actions.open(
                        RecoveryAction(
                            id=mint_id(),
                            source_task_id=task.id,
                            kind=RecoveryKind.STRANDED,
                            owner_employee_id=employee.id,
                            cause="integrate_iteration_exhausted",
                            fingerprint="integrate_iteration",
                            evidence=evidence,
                            next_action="human review of delegated objective and Team plan",
                        )
                    )
            ledger.tasks.release_locks(task.id, run_id=run_id)
            ledger.wakes.mark_done(wake.id)
            return True
        verifier = ledger.dod.verifier_for_task(task.id)
        beat_runner_for = self._require(self._beat_runner_for, "beat_runner")
        beat_runner = beat_runner_for.runner_for(employee, task_id=task.id)
        ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=None)
        if (
            self._integrate_floor_verdict(task.id, verifier=verifier, beat_runner=beat_runner)
            is False
        ):
            # The cap bounds the MODEL loop (no further decompose/integrate beats), NOT the objective
            # gate: even here a parent does not land ``done`` while its ``command`` rollup floor fails —
            # record the failed verdict and park BLOCKED rather than fabricate a passing outcome.
            ledger.finalize_beat(
                task_id=task.id, run_id=run_id, dod_status=DodStatus.FAILED, verdict=None
            )
            ledger.tasks.set_status(task.id, TaskStatus.BLOCKED)
        else:
            await self._land_passed(
                task.id,
                run_id=run_id,
                verifier=verifier,
                verdict=None,
                employee=employee,
                result=BeatOutcome(
                    passed=True, outcome={}, summary="integrated (iteration cap reached)"
                ),
                outcome_kind=(
                    execution_profile.outcome_kind if execution_profile is not None else None
                ),
                now=now,
            )
        ledger.tasks.release_locks(task.id, run_id=run_id)
        ledger.wakes.mark_done(wake.id)
        return True

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
        outcome_kind: str | None,
        now: datetime,
    ) -> None:
        """A passed beat lands its role's outcome, then ``done`` — unless a person or reviewer decides.

        For a ``HumanApproval`` DoD the deliverable is produced but a person decides: open an
        **acceptance** gate (parks the task ``blocked`` pending the approval). For a ``ReviewedBuild``
        DoD on a *leaf* deliverable, a read-only Reviewer beat discovers + runs the objective command
        floor that gates completion (a delegated subtree integrates mechanically and is excluded). An
        ``AgentReview`` DoD renders no second beat: its rubric was already judged by dream's single
        in-beat evaluator (spec 16), so a passed beat *is* the verdict. Otherwise the role's
        :class:`~chorus.outcomes.OutcomeLander` records the deliverable before the task is finalised ``done``.
        """
        ledger = self._require_ledger()
        # A gate opened *during* the beat (e.g. the marketer's ``stage_go_live`` tool) must win over the
        # DoD: a task carrying a pending approval is parked BLOCKED, not finalised ``done`` — resolving
        # the gate is what completes it. Explicitly (re-)block here rather than trusting the mid-run
        # ``open_task_gate`` transition to survive the run's own lifecycle, which leaves the task
        # ``in_progress``. Without this the DoD races the gate to ``done`` (or leaves it ``in_progress``)
        # and the gate's approval path (blocked → todo) then hits an illegal ``… → todo``. Checked
        # before the DoD branches so it guards every gated path.
        if any(approval.subject_id == task_id for approval in ledger.approvals.pending()):
            task = ledger.tasks.get(task_id)
            if task is not None and task.status is not TaskStatus.BLOCKED:
                ledger.tasks.transition(task_id, TaskStatus.BLOCKED)
            return
        if verifier is not None and verifier.kind is DoDKind.HUMAN_APPROVAL:
            GovernanceResolver(ledger).open_task_gate(
                task_id,
                gate_kind=ApprovalGate.ACCEPTANCE,
                reason=f"human-approval DoD for {task_id}",
            )
            return
        if (
            verifier is not None
            and verifier.kind in _REVIEWER_GATED_DODS
            and not ledger.tasks.has_children(task_id)
        ):
            await self._run_review(
                task_id,
                verifier=verifier,
                author=employee,
                work_result=result,
                author_outcome_kind=outcome_kind,
                now=now,
            )
            return
        await self._land_outcome(
            task_id, employee=employee, result=result, outcome_kind=outcome_kind
        )
        ledger.finalize_beat(
            task_id=task_id, run_id=run_id, dod_status=DodStatus.PASSED, verdict=verdict
        )

    async def _run_review(
        self,
        task_id: str,
        *,
        verifier: Verifier,
        author: Employee,
        work_result: BeatOutcome,
        author_outcome_kind: str | None,
        now: datetime,
    ) -> None:
        """Dispatch a read-only Reviewer beat as the verification step for a reviewer-gated DoD.

        The reviewer inspects the work in the author's worktree and calls ``submit_verdict``, recording
        the work task's DoD verdict. The kernel reads it back: a quality ``approve`` lands the deliverable
        (for a ``reviewed_build`` it first runs the reviewer-discovered command as the objective floor); a
        ``block`` routes per :meth:`_route_block`. The verifier is a built-in system principal, never a
        workforce member and never the author.
        """
        ledger = self._require_ledger()
        rubric = _review_rubric(verifier.spec)
        reviewer = SYSTEM_VERIFIER

        review_run_id = mint_id()
        runner = self._review_runner(reviewer, task_id=task_id, worktree_owner_id=author.id)
        ledger.runs.create(
            Run(
                id=review_run_id,
                employee_id=author.id,
                task_id=task_id,
                principal_kind="system",
                system_principal_id=reviewer.id,
                status=RunStatus.RUNNING,
                # A lease, like every other running beat: a null lease reads as crash debris to the
                # stale-run reaper (a concurrent RECOVER under run_forever, or another Arceus worker),
                # which would reap this in-flight review and strand the deliverable (spec 03 §5).
                lease_expires_at=now + timedelta(seconds=self.lease_ttl_s),
                started_at=now,
            )
        )
        worktree = runner.working_dir if isinstance(runner, _RunnerWithWorkingDir) else None
        if worktree is not None:
            BeatContext(task_id=task_id, run_id=review_run_id, employee_id=reviewer.id).write(
                worktree
            )
        observer = (
            TraceStamper(
                self._event_bus.emit,
                trace_id=trace_root(ledger, task_id),
                task_id=task_id,
                employee_id=reviewer.id,
                run_id=review_run_id,
            )
            if self._event_bus is not None
            else None
        )
        try:
            result = await runner.run_task(
                task_id=task_id,
                run_id=review_run_id,
                intent=self._review_intent(task_id, verifier, rubric, worktree=worktree),
                observer=observer,
            )
        except Exception as exc:
            result = failure_outcome(exc)
        ledger.runs.finish(review_run_id, RunStatus.SUCCEEDED, outcome=result.outcome or None)

        dod = ledger.dod.get_for_task(task_id)
        if dod is None or dod.status is DodStatus.PENDING:
            # The reviewer beat rendered no verdict (it never called ``submit_verdict``). Don't silently
            # pass it and don't loop self-repair forever — a human looks at why the reviewer stalled.
            ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            self._open_review_recovery(task_id, cause="no_verdict", owner_id=author.id)
            return
        if dod.status is not DodStatus.PASSED:  # the reviewer blocked on quality
            await self._land_outcome(task_id, employee=None, result=result, outcome_kind="verdict")
            self._route_block(task_id, author=author)
            return
        # Quality approved. A reviewed_build still has an objective floor: the kernel runs the
        # reviewer-discovered command — passing it never depends on the model's word.
        if verifier.kind is DoDKind.REVIEWED_BUILD and not self._reviewed_build_passes(
            task_id,
            dod_id=dod.id,
            run_id=review_run_id,
            verifier=verifier,
            verdict=dod.verdict,
            worktree=worktree,
        ):
            await self._land_outcome(task_id, employee=None, result=result, outcome_kind="verdict")
            self._route_block(task_id, author=author)
            return
        await self._land_outcome(
            task_id, employee=None, result=result, outcome_kind="verdict"
        )  # the `verdict` artifact
        await self._land_outcome(
            task_id,
            employee=author,
            result=work_result,
            outcome_kind=author_outcome_kind,
        )
        dod_after = ledger.dod.get_for_task(task_id)
        ledger.finalize_beat(
            task_id=task_id,
            run_id=review_run_id,
            dod_status=DodStatus.PASSED,
            verdict=dod_after.verdict if dod_after is not None else dod.verdict,
        )

    def _reviewed_build_passes(
        self,
        task_id: str,
        *,
        dod_id: str,
        run_id: str,
        verifier: Verifier,
        verdict: dict[str, object] | None,
        worktree: Path | None,
    ) -> bool:
        """Validate configured evidence, then run the project command as a separate objective floor.

        Returns ``True`` iff both configured floors pass. Failures are recorded on the DoD verdict and
        block landing without relying on model-composed shell fragments."""
        ledger = self._require_ledger()
        command = str((verdict or {}).get("verify_command", "")).strip()
        timeout_s = (
            verifier.spec.verify_timeout_s if isinstance(verifier.spec, ReviewedBuild) else 600
        )
        evidence: dict[str, object] = {}
        profile = (
            verifier.spec.evidence_profile if isinstance(verifier.spec, ReviewedBuild) else None
        )
        if profile is not None:
            if worktree is None:
                evidence = {
                    "evidence_passed": False,
                    "evidence_output": "no worktree to validate structured evidence in",
                }
            elif profile is ReviewedBuildEvidenceProfile.TDD_REVIEW_V1:
                evidence_passed, evidence_output = _tdd_review_evidence_passes(worktree)
                evidence = {
                    "evidence_passed": evidence_passed,
                    "evidence_output": evidence_output,
                }
            if evidence.get("evidence_passed") is not True:
                ledger.dod.record_verdict(
                    dod_id,
                    DodStatus.FAILED,
                    verdict={**(verdict or {}), **evidence, "build_passed": False},
                    run_id=run_id,
                )
                return False
        if not command or worktree is None:
            reason = (
                "reviewer approved but supplied no verify command"
                if not command
                else ("no worktree to run the verify command in")
            )
            ledger.dod.record_verdict(
                dod_id,
                DodStatus.FAILED,
                verdict={
                    **(verdict or {}),
                    **evidence,
                    "build_passed": False,
                    "build_output": reason,
                },
                run_id=run_id,
            )
            return False
        exit_code, output = _run_verify_command(worktree, command, timeout_s=timeout_s)
        ledger.dod.record_verdict(
            dod_id,
            DodStatus.PASSED if exit_code == 0 else DodStatus.FAILED,
            verdict={
                **(verdict or {}),
                **evidence,
                "build_passed": exit_code == 0,
                "build_exit": exit_code,
                "build_output": output,
            },
            run_id=run_id,
        )
        return exit_code == 0

    def _route_block(self, task_id: str, *, author: Employee) -> None:
        """Route a reviewer ``block`` — escalate to a manager parent, else bounded author self-repair.

        A child of a manager → mark it ``rejected`` (terminal) and, once the subtree is wholly terminal,
        wake the manager: its Slice-2 integrate beat sees the rejection and reacts (``submit_task`` /
        ``assign_task``). A standalone deliverable → re-dispatch the author up to ``max_review_rounds``,
        then open a recovery card for a human.
        """
        ledger = self._require_ledger()
        task = ledger.tasks.get(task_id)
        if task is None:
            return
        manager_id = self._manager_of(task)
        if manager_id is not None:
            ledger.tasks.set_status(task_id, TaskStatus.REJECTED)
            if task.parent_id is not None and ledger.tasks.all_children_terminal(task.parent_id):
                ledger.wakes.enqueue(
                    Wake(
                        id=mint_id(),
                        employee_id=manager_id,
                        reason=WakeReason.CHILDREN_DONE,
                        payload={"task_id": task.parent_id},
                    )
                )
            return
        # Count the author's actual rework attempts — robust whether the rejection was a quality block
        # or a failed build (a build-fail is the reviewer approving + the kernel-run command failing).
        attempts = sum(1 for run in ledger.runs.for_task(task_id) if run.employee_id == author.id)
        if attempts <= self.max_review_rounds:
            ledger.tasks.set_status(task_id, TaskStatus.TODO)  # re-dispatch the author to fix it
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
                    employee_id=author.id,
                    reason=WakeReason.RECOVERY,
                    payload={"task_id": task_id, "cause": "review_blocked"},
                )
            )
            return
        ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
        self._open_review_recovery(task_id, cause="review_exhausted", owner_id=author.id)

    def _manager_of(self, task: Task) -> str | None:
        """The employee id of the task's manager (its parent's assignee), or ``None`` if standalone."""
        if task.parent_id is None:
            return None
        ledger = self._require_ledger()
        parent = ledger.tasks.get(task.parent_id)
        return parent.assignee_employee_id if parent is not None else None

    def _review_runner(
        self, reviewer: VerificationPrincipal, *, task_id: str, worktree_owner_id: str
    ) -> BeatRunner:
        """Resolve a reviewer runner at the author's worktree, else its own (a non-review-aware seam)."""
        beat_runner_for = self._require(self._beat_runner_for, "beat_runner")
        if isinstance(beat_runner_for, _ReviewRunnerFor):
            return beat_runner_for.review_runner_for(
                reviewer, task_id=task_id, worktree_owner_id=worktree_owner_id
            )
        return beat_runner_for.runner_for(reviewer, task_id=task_id)  # type: ignore[arg-type]

    def _verification_runner(
        self, reviewer: VerificationPrincipal, *, task_id: str, worktree_owner_id: str
    ) -> BeatRunner:
        """Resolve the strict verifier seam, with compatibility fallbacks for test runners."""
        beat_runner_for = self._require(self._beat_runner_for, "beat_runner")
        if isinstance(beat_runner_for, _VerificationRunnerFor):
            return beat_runner_for.verification_runner_for(
                reviewer,
                task_id=task_id,
                worktree_owner_id=worktree_owner_id,
            )
        if isinstance(beat_runner_for, _ReviewRunnerFor):
            return beat_runner_for.review_runner_for(
                reviewer,
                task_id=task_id,
                worktree_owner_id=worktree_owner_id,
            )
        return beat_runner_for.runner_for(reviewer, task_id=task_id)  # type: ignore[arg-type]

    def _review_intent(
        self, task_id: str, verifier: Verifier, rubric: str, *, worktree: Path | None = None
    ) -> str:
        """The reviewer beat's instruction: judge the work in the worktree against the rubric.

        For a ``reviewed_build`` the reviewer also discovers the project's verify command and passes it
        as ``verify_command`` — the kernel runs it as the objective floor, so the reviewer never runs it.

        The reviewer has no directory-listing tool, so the kernel embeds the worktree's file manifest:
        without it the reviewer guesses standard filenames, misses the author's actual files, and wrongly
        judges the work empty.
        """
        ledger = self._require_ledger()
        task = ledger.tasks.get(task_id)
        goal = task.intent if task is not None else task_id
        rubric_line = rubric or "the task is complete, correct, and meets its stated intent"
        build = ""
        if verifier.kind is DoDKind.REVIEWED_BUILD:
            evidence_instruction = ""
            if (
                isinstance(verifier.spec, ReviewedBuild)
                and verifier.spec.evidence_profile is not None
            ):
                evidence_instruction = (
                    "Pass only the repository's exact configured build/test command as "
                    "`verify_command`; do not append grep, test -f, PowerShell, or other evidence-file "
                    "checks. The kernel parses the configured structured evidence separately. "
                )
            build = (
                "This is a code task: inspect the project's files (package.json / Cargo.toml / "
                "pyproject.toml / Makefile / go.mod, etc.) to determine the correct command that builds + "
                "tests it, and pass that as `verify_command` (e.g. 'npm ci && npm test', 'cargo test', "
                "'pytest -q'). The kernel runs it as the objective gate — you do not run it yourself, and "
                "you CANNOT run it (you are read-only). Do NOT block merely because you could not execute "
                "the tests: judge the diff's correctness against the contract by reading it; if the code is "
                "correct, approve=true and pass the command — the kernel runs it and will fail the build if "
                "the tests do not pass. "
                f"{evidence_instruction}"
                "Reserve approve=false for a concrete correctness defect you can name.\n"
            )
        manifest = _worktree_file_manifest(worktree)
        files = (
            "Files in this worktree (read the relevant ones with `read_file`; you have no listing tool, "
            f"so this is the authoritative inventory of what is here):\n{manifest}\n"
            if manifest
            else ""
        )
        return (
            f"You are reviewing the work in this worktree for the task: {goal}\n"
            f"Rubric: {rubric_line}\n"
            f"{files}"
            f"{build}"
            "Read the relevant files to judge it. You MUST finish by calling the `submit_verdict` tool "
            "exactly once — that tool call IS your review and the ONLY way to complete this task. Pass "
            "approve=true to accept or approve=false to block, with concrete feedback. Do NOT just write "
            "your verdict as text; an un-recorded verdict does not count."
        )

    def _open_review_recovery(self, task_id: str, *, cause: str, owner_id: str) -> None:
        """Open a recovery card for a reviewed task a human must now resolve (idempotent per source)."""
        ledger = self._require_ledger()
        if ledger.recovery_actions.active_for_source(task_id) is not None:
            return
        ledger.recovery_actions.open(
            RecoveryAction(
                id=mint_id(),
                source_task_id=task_id,
                kind=RecoveryKind.STRANDED,
                owner_employee_id=owner_id,
                cause=cause,
                fingerprint="review",
                next_action="resolve the rejected deliverable or revise its DoD",
            )
        )

    def _lease_seconds_for(
        self,
        employee: Employee,
        *,
        execution_profile: ResolvedExecutionProfile | None = None,
    ) -> float:
        """The run-lease TTL for a beat of ``employee``'s role — the role's override, else the default.

        A research-heavy role (one that spawns a multi-minute ``web_research`` sweep in a single
        uninterrupted call, unable to renew its lease meanwhile) sets a larger ``lease_ttl_s`` so the
        stale-run reaper doesn't claim its still-live beat at the org default (spec 06 §2).
        """
        if execution_profile is not None and execution_profile.config.lease_ttl_s is not None:
            return execution_profile.config.lease_ttl_s
        if self._roles is not None and employee.role in self._roles:
            ttl = self._roles.get(employee.role).manifest.lease_ttl_s
            if ttl is not None:
                return ttl
        return self.lease_ttl_s

    async def _land_outcome(
        self,
        task_id: str,
        *,
        employee: Employee | None,
        result: BeatOutcome,
        outcome_kind: str | None = None,
    ) -> None:
        """Record the role's deliverable as an artifact via its registered lander (spec 04 §2).

        A no-op when no lander registry is wired or the employee's role lands no artifact kind — the
        beat still finalises ``done``, so landing is purely additive (the strict-completion record).
        """
        if self._landers is None:
            return
        if outcome_kind is None:
            if employee is None or self._roles is None or employee.role not in self._roles:
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

        A ``needs-changes`` beat means the step isn't done yet — so re-wake the same assignee to resume
        it: a ``Command`` DoD re-runs its objective gate, a ``reviewed_build``/``agent_review`` continues
        its (multi-sprint) build (spec 05, one-beat-one-sprint). Rung 1 (budget left) keeps the task
        ``todo`` with a live recovery wake, so the recovery sweep leaves it alone; rung 3 (budget spent)
        sets ``blocked`` + a ``recovery_action`` for a human. A task with **no** DoD has no objective
        step to resume, so it blocks straight away.
        """
        ledger = self._require_ledger()
        if verifier is None:
            ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            return
        failures = sum(1 for run in ledger.runs.for_task(task_id) if run.status is RunStatus.FAILED)
        if failures <= self.max_repair_attempts:
            ledger.tasks.set_status(task_id, TaskStatus.TODO)  # dispatchable; not yet "stuck"
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id(),
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
                    id=mint_id(),
                    source_task_id=task_id,
                    kind=RecoveryKind.STALE_RUN_WATCHDOG,
                    owner_employee_id=employee_id,
                    cause="dod_repair_exhausted",
                    fingerprint="dod",
                    next_action="fix the failing check or revise the DoD",
                )
            )

    def _resume_or_strand(self, task_id: str, *, employee_id: str, result: BeatOutcome) -> None:
        """A wall-clock TIMEOUT RESUMES the same task; any other engine fault strands (resumption Slice B).

        Budget exhaustion is unfinished-not-wrong: the persistent worktree — and the ``TODO.md``
        checklist ``todo_write`` left in it — survive, so re-dispatching the SAME task to the SAME
        employee lets the next beat reconcile the checklist against git+tests and continue. Bounded by
        ``max_resume_attempts`` (counted over the task's timed-out runs, NOT the DoD repair budget);
        once spent, repeated exhaustion means the task is too big for one beat, so it strands for a human.
        """
        ledger = self._require_ledger()
        is_timeout = "TimeoutError" in str(result.outcome.get("error", ""))
        if is_timeout:
            timeouts = sum(
                1
                for run in ledger.runs.for_task(task_id)
                if run.status is RunStatus.FAILED and "TimeoutError" in str(run.outcome)
            )
            if timeouts <= self.max_resume_attempts:
                ledger.tasks.set_status(task_id, TaskStatus.TODO)  # re-dispatchable; not stuck
                ledger.wakes.enqueue(
                    Wake(
                        id=mint_id(),
                        employee_id=employee_id,
                        reason=WakeReason.RECOVERY,
                        payload={"task_id": task_id, "cause": "budget_resume"},
                    )
                )
                return
        self._strand_errored(task_id, employee_id=employee_id, result=result)

    def _strand_errored(self, task_id: str, *, employee_id: str, result: BeatOutcome) -> None:
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
                id=mint_id(),
                source_task_id=task_id,
                kind=RecoveryKind.STRANDED,
                owner_employee_id=employee_id,
                cause="run_task_error",
                fingerprint=str(phase) if phase else "engine",
                evidence={"phase": phase, "error": result.outcome.get("error")},
                next_action="inspect the engine fault and resume or hand off the task",
            )
        )

    def _emit_allocation(
        self,
        kind: EventKind,
        *,
        at: datetime,
        task_id: str,
        employee_id: str,
        run_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        """Mirror one allocation transition onto the bus (OBS P6) — no bus, no-op."""
        if self._event_bus is None:
            return
        self._event_bus.emit(
            Event(
                kind=kind,
                at=at,
                trace_id=trace_root(self._require_ledger(), task_id),
                task_id=task_id,
                employee_id=employee_id,
                run_id=run_id,
                payload=payload or {},
            )
        )

    def _record_cost(
        self,
        employee_id: str,
        *,
        task_id: str,
        run_id: str,
        trace_id: str,
        result: BeatOutcome,
        now: datetime,
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
                id=mint_id(),
                employee_id=employee_id,
                task_id=task_id,
                run_id=run_id,
                provider="dream",
                model=result.model,
                cost_cents=result.cost_cents,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                trace_id=trace_id,
                occurred_at=now,
            )
        )
        if self._budget_enforcer is not None:
            self._budget_enforcer.on_cost_event(event, now=now)

    def _require_ledger(self) -> Ledger:
        return self._require(self._ledger, "ledger")

    @staticmethod
    def _require(seam: _T | None, name: str) -> _T:
        if seam is None:
            raise RuntimeError(f"Scheduler not wired with a {name} (inject it at construction)")
        return seam

    @staticmethod
    def sort_key(
        *,
        in_progress: bool,
        deps_done: bool,
        priority: TaskPriority,
        created_at: datetime,
        wake_id: str,
    ) -> tuple[int, int, int, datetime, str]:
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
