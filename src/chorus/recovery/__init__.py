"""Liveness & recovery - "who owns making this unstuck" (spec 02 §6-§7, §9).

Recovery is **liveness-as-visibility**: a non-terminal task that has lost its action-path
primitive becomes a first-class :class:`~chorus.ledger.RecoveryAction` naming an owner, a
cause, and the next move - surfaced, never silently dropped. :func:`reconcile` is a pure
function of the ledger (re-derived from rows, idempotent across crash+restart) running the
ordered tick sweep (spec 02 §7):

1. **reap** orphaned ``running`` runs whose lease passed - release the checkout lock and mark
   the run timed-out. This is *crash recovery, not retry*: a live owner is left alone (the
   compare-and-clear only releases a lock still pointing at the dead run, spec 01 invariant 4).
2. **reconcile stranded** assigned work via the bounded three-tier ladder (spec 02 §6):
   *auto-recover* (only execution continuity lost -> enqueue ONE dispatch/continuation wake,
   owner PRESERVED); then, if that wake was delivered and the task is *still* stranded,
   *explicit recovery* (escalate to ``blocked`` + a typed ``recovery_action``).
3. **fold** open recoveries whose source went terminal (source-aware folding) - resolve the
   alert as a false positive rather than nag about already-finished work.

It never auto-reassigns to a different employee and never treats human-held work as
beat-managed (spec 02 §8).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    RecoveryAction,
    RecoveryKind,
    RecoveryOutcome,
    RunStatus,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
    WakeStatus,
)
from chorus.lifecycle import classify

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

# The cheap-model recovery lane (spec 02 §9.3): status-only overhead carries guard context so a
# recovery beat can't quietly resume deliverable work - it must hand back to a normal run.
_CHEAP_LANE: dict[str, object] = {
    "lane": "cheap",
    "allow_deliverable_work": False,
    "allow_document_updates": False,
    "resume_requires_normal": True,
}

# Stalled reasons that map to the two §9 crash modes (a wake can resume the lost dispatch).
_DISPATCH_RECOVERY: dict[str, str] = {
    "stranded_todo": "assignment_recovery",
    "stranded_in_progress": "continuation",
}


@dataclass(frozen=True)
class ReconcileReport:
    """What one :func:`reconcile` pass did - empty lists mean a quiet, fully-recovered ledger."""

    reaped_runs: list[str] = field(default_factory=list)
    recovered: list[str] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    folded: list[str] = field(default_factory=list)


def reconcile(ledger: SqliteLedger, *, now: datetime) -> ReconcileReport:
    """Run one ordered recovery sweep over the ledger (spec 02 §7); see module docstring."""
    reaped = _reap_orphaned_runs(ledger, now=now)
    recovered, opened = _reconcile_stranded(ledger, now=now)
    folded = _fold_terminal_sources(ledger)
    return ReconcileReport(
        reaped_runs=reaped, recovered=recovered, opened=opened, folded=folded
    )


# -- §7 step 1: reap orphaned running runs ------------------------------------


def _reap_orphaned_runs(ledger: SqliteLedger, *, now: datetime) -> list[str]:
    reaped: list[str] = []
    for run in ledger.runs.running_with_expired_lease(now):
        with ledger.transaction():
            ledger.tasks.release_locks(run.task_id, run_id=run.id)
            ledger.runs.finish(run.id, RunStatus.TIMED_OUT, liveness_state="reaped")
        reaped.append(run.id)
    return reaped


# -- §7 step 3: reconcile stranded assigned work (the §6 ladder) --------------


def _reconcile_stranded(
    ledger: SqliteLedger, *, now: datetime
) -> tuple[list[str], list[str]]:
    recovered: list[str] = []
    opened: list[str] = []
    for task in ledger.tasks.agent_owned_open():
        live = classify(task, ledger, now=now)
        if live.healthy:
            continue  # a live wake / open recovery already keeps it healthy
        # A blocked task stalled *because of a blocker* is handled when we reach that leaf.
        if live.reason.startswith("stalled_blocker_leaf:"):
            continue

        kind = _DISPATCH_RECOVERY.get(live.reason)
        if kind is None:
            # No dispatch to retry (in_review / blocked-no-blocker): open a card directly.
            action_id = _open_recovery(ledger, task, cause=live.reason)
            if action_id is not None:
                opened.append(action_id)
            continue

        # Tier 1 -> Tier 2 ladder: one wake, then escalate once it's delivered + still stranded.
        key = _recovery_key(task.id)
        delivered = any(
            w.status is WakeStatus.DONE for w in ledger.wakes.by_coalesce_key(key)
        )
        if delivered:
            action_id = _escalate(ledger, task, cause=live.reason)
            if action_id is not None:
                opened.append(action_id)
        else:
            _enqueue_recovery_wake(ledger, task, kind=kind, key=key)
            recovered.append(task.id)
    return recovered, opened


def _enqueue_recovery_wake(
    ledger: SqliteLedger, task: Task, *, kind: str, key: str
) -> None:
    ledger.wakes.enqueue(
        Wake(
            id=f"wake_{uuid.uuid4().hex[:12]}",
            employee_id=task.assignee_employee_id,  # type: ignore[arg-type]  # agent-owned scan
            reason=WakeReason.RECOVERY,
            payload={"kind": kind, "task_id": task.id, **_CHEAP_LANE},
            coalesce_key=key,
        )
    )


def _escalate(ledger: SqliteLedger, task: Task, *, cause: str) -> str | None:
    """Exhausted ladder: surface the stuck task as ``blocked`` + a recovery owner (spec 02 §6)."""
    if ledger.recovery_actions.active_for_source(task.id) is not None:
        return None
    action_id = f"rec_{uuid.uuid4().hex[:12]}"
    with ledger.transaction():
        if task.status is not TaskStatus.BLOCKED:
            ledger.tasks.transition(task.id, TaskStatus.BLOCKED)
        ledger.recovery_actions.open(
            RecoveryAction(
                id=action_id,
                source_task_id=task.id,
                kind=RecoveryKind.STRANDED,
                owner_employee_id=task.assignee_employee_id,
                cause=cause,
                fingerprint="recovery",
                next_action="resume or hand off the stranded task",
            )
        )
    return action_id


def _open_recovery(ledger: SqliteLedger, task: Task, *, cause: str) -> str | None:
    """Open an explicit recovery card without a status change (the card IS the live path)."""
    if ledger.recovery_actions.active_for_source(task.id) is not None:
        return None
    action_id = f"rec_{uuid.uuid4().hex[:12]}"
    ledger.recovery_actions.open(
        RecoveryAction(
            id=action_id,
            source_task_id=task.id,
            kind=RecoveryKind.STRANDED,
            owner_employee_id=task.assignee_employee_id,
            cause=cause,
            fingerprint="recovery",
            next_action="resolve the stalled task or hand it off",
        )
    )
    return action_id


# -- §7 step 4 / §6: source-aware folding -------------------------------------


def _fold_terminal_sources(ledger: SqliteLedger) -> list[str]:
    folded: list[str] = []
    for action in ledger.recovery_actions.all_open():
        source = ledger.tasks.get(action.source_task_id)
        if source is None or source.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            ledger.recovery_actions.resolve(
                action.id,
                outcome=RecoveryOutcome.FALSE_POSITIVE,
                resolution_note="source terminal",
            )
            folded.append(action.id)
    return folded


def _recovery_key(task_id: str) -> str:
    return f"recovery:{task_id}"


__all__ = [
    "ReconcileReport",
    "reconcile",
]
