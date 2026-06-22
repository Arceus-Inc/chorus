"""The liveness contract (spec 02 §3) — when is a task *healthy*?

An agent-owned, non-terminal task is **healthy** iff it has at least one
**action-path primitive** (``execution-semantics.md`` §8); otherwise it is
**stalled** and must be surfaced as recovery work — never silently completed or
reassigned. This is a *visibility* contract, not an auto-completion one.

:func:`classify` is a pure read over the ledger: it never mutates. The tick's
recovery sweep (spec 02 §6-§7, Phase 4) consumes it to decide what to open.

Per-status primitives (spec 02 §3):
- **todo** - a queued wake, OR resting after a non-interrupted run; *stalled* only
  when a dispatch was interrupted (last run failed/timed-out/cancelled) and nothing
  remains queued and no recovery is open.
- **in_progress** - an active run *within lease*, OR a queued continuation, OR an
  active monitor, OR an open recovery. A quiet-but-leased run is **not** stalled.
- **in_review** - a pending approval (the review path), OR an active run / queued
  wake / active monitor / open recovery. A bare "please review" comment is not a path.
- **blocked** - an open recovery, a pending approval, an active monitor, OR a
  first-class blocker chain whose unresolved *leaf* is itself healthy; an
  intermediate blocked task does not make the chain healthy - surface the first
  stalled leaf.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    ApprovalSubjectKind,
    RunStatus,
    Task,
    TaskStatus,
)

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

class Health(StrEnum):
    """Whether a task currently has a live path forward (spec 02 §3)."""

    HEALTHY = "healthy"
    STALLED = "stalled"


@dataclass(frozen=True)
class Liveness:
    """The verdict + the primitive (or cause) behind it (spec 02 §3)."""

    health: Health
    reason: str

    @property
    def healthy(self) -> bool:
        return self.health is Health.HEALTHY

    @property
    def stalled(self) -> bool:
        return self.health is Health.STALLED


def classify(task: Task, ledger: SqliteLedger, *, now: datetime) -> Liveness:
    """Return the :class:`Liveness` of ``task`` as of ``now`` (pure read, spec 02 §3)."""
    return _classify(task, ledger, now=now, seen=set())


def _classify(
    task: Task, ledger: SqliteLedger, *, now: datetime, seen: set[str]
) -> Liveness:
    # Universal short circuits (spec 02 §3): terminal, human-owned, parked.
    if task.status in (TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED):
        return Liveness(Health.HEALTHY, "terminal")
    if task.assignee_user_id is not None:
        return Liveness(Health.HEALTHY, "human_owner")
    if task.status is TaskStatus.BACKLOG:
        return Liveness(Health.HEALTHY, "backlog_parked")

    if task.status is TaskStatus.TODO:
        return _classify_todo(task, ledger)
    if task.status is TaskStatus.IN_PROGRESS:
        return _classify_in_progress(task, ledger, now=now)
    if task.status is TaskStatus.IN_REVIEW:
        return _classify_in_review(task, ledger, now=now)
    return _classify_blocked(task, ledger, now=now, seen=seen)


def _classify_todo(task: Task, ledger: SqliteLedger) -> Liveness:
    if _has_live_wake(task, ledger):
        return Liveness(Health.HEALTHY, "queued_wake")
    if _has_open_recovery(task, ledger):
        return Liveness(Health.HEALTHY, "open_recovery")
    if _has_active_monitor(task, ledger):
        return Liveness(Health.HEALTHY, "active_monitor")
    # "Resting" is the post-success lull — a beat ran, succeeded, and left the task queued for its next
    # step. It is the ONLY healthy todo lacking a live wake/recovery/monitor. A todo whose last run was
    # interrupted (failed/timed-out/cancelled) OR that was *never dispatched at all* (no runs — its
    # ``assign_task`` wake was lost) has no path forward and is stranded (spec 02 §9, paperclip's
    # ``hasExplicitWaitingPath``). Without this, a never-dispatched child reads "resting" healthy and
    # silently hangs its blocked parent forever.
    if _last_run_succeeded(task, ledger):
        return Liveness(Health.HEALTHY, "resting")
    return Liveness(Health.STALLED, "stranded_todo")


def _classify_in_progress(task: Task, ledger: SqliteLedger, *, now: datetime) -> Liveness:
    if _has_active_run(task, ledger, now=now):
        return Liveness(Health.HEALTHY, "active_run")
    if _has_live_wake(task, ledger):
        return Liveness(Health.HEALTHY, "queued_continuation")
    if _has_active_monitor(task, ledger):
        return Liveness(Health.HEALTHY, "active_monitor")
    if _has_open_recovery(task, ledger):
        return Liveness(Health.HEALTHY, "open_recovery")
    return Liveness(Health.STALLED, "stranded_in_progress")


def _classify_in_review(task: Task, ledger: SqliteLedger, *, now: datetime) -> Liveness:
    if _has_pending_approval(task, ledger):
        return Liveness(Health.HEALTHY, "pending_approval")
    if _has_active_run(task, ledger, now=now):
        return Liveness(Health.HEALTHY, "active_run")
    if _has_live_wake(task, ledger):
        return Liveness(Health.HEALTHY, "queued_wake")
    if _has_active_monitor(task, ledger):
        return Liveness(Health.HEALTHY, "active_monitor")
    if _has_open_recovery(task, ledger):
        return Liveness(Health.HEALTHY, "open_recovery")
    return Liveness(Health.STALLED, "stranded_in_review")


def _classify_blocked(
    task: Task, ledger: SqliteLedger, *, now: datetime, seen: set[str]
) -> Liveness:
    if _has_open_recovery(task, ledger):
        return Liveness(Health.HEALTHY, "open_recovery")
    if _has_pending_approval(task, ledger):
        return Liveness(Health.HEALTHY, "pending_approval")
    if _has_active_monitor(task, ledger):
        return Liveness(Health.HEALTHY, "active_monitor")
    # A queued/claimed wake means the scheduler is about to re-dispatch this task — it is not stalled.
    # This is the parked-manager case (M3): once its children land, a `blocked` parent's blockers
    # resolve but it holds a queued `children_done` wake pending the integrate beat. Without this the
    # reconcile sweep would strand the parked parent (``blocked_no_blocker``) before it integrates.
    if _has_live_wake(task, ledger):
        return Liveness(Health.HEALTHY, "queued_wake")

    unresolved = ledger.dependencies.unresolved_blockers(task.id)
    if not unresolved:
        # blocked but nothing names the blocker/owner — the first stalled leaf is itself (§3).
        return Liveness(Health.STALLED, "blocked_no_blocker")
    seen.add(task.id)
    for blocker_id in unresolved:
        if blocker_id in seen:
            continue
        blocker = ledger.tasks.get(blocker_id)
        if blocker is None:
            continue
        leaf = _classify(blocker, ledger, now=now, seen=seen)
        if leaf.stalled:
            return Liveness(Health.STALLED, f"stalled_blocker_leaf:{blocker_id}")
    return Liveness(Health.HEALTHY, "healthy_blocker")


# -- primitive probes ---------------------------------------------------------


def _has_active_run(task: Task, ledger: SqliteLedger, *, now: datetime) -> bool:
    """A ``running`` run whose lease has not expired (spec 02 §3 lease clock)."""
    for run in ledger.runs.for_task(task.id):
        if (
            run.status is RunStatus.RUNNING
            and run.lease_expires_at is not None
            and run.lease_expires_at > now
        ):
            return True
    return False


def _has_live_wake(task: Task, ledger: SqliteLedger) -> bool:
    """A queued/claimed wake for the assignee that targets this task."""
    if task.assignee_employee_id is None:
        return False
    return any(
        wake.payload.get("task_id") == task.id
        for wake in ledger.wakes.active_for_employee(task.assignee_employee_id)
    )


def _has_active_monitor(task: Task, ledger: SqliteLedger) -> bool:
    return ledger.monitors.armed_for_task(task.id) is not None


def _has_pending_approval(task: Task, ledger: SqliteLedger) -> bool:
    return any(
        ap.subject_kind is ApprovalSubjectKind.TASK and ap.subject_id == task.id
        for ap in ledger.approvals.pending()
    )


def _has_open_recovery(task: Task, ledger: SqliteLedger) -> bool:
    return ledger.recovery_actions.active_for_source(task.id) is not None


def _last_run_succeeded(task: Task, ledger: SqliteLedger) -> bool:
    """True iff the task's latest run completed successfully (spec 02 §9).

    The post-success lull is the only "resting" a todo may have without a live wake. A todo with no
    runs at all (never dispatched) or whose last run was interrupted is *not* resting — it is stranded.
    """
    runs = ledger.runs.for_task(task.id)
    return bool(runs) and runs[-1].status is RunStatus.SUCCEEDED


__all__ = [
    "Health",
    "Liveness",
    "classify",
]
