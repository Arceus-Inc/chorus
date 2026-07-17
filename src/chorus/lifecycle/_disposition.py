"""The valid-disposition contract (spec 02 §5).

"Finished" requires the task *state/path* to record a valid disposition, not just a transcript.
:func:`reconcile_disposition` enforces that: when a run **succeeded** but left the task
``in_progress`` with no human owner and no live path, it enqueues **one** corrective
finish-handoff wake (the employee must pick ``done``/``cancelled`` / a real ``in_review`` path /
``blocked`` with first-class blockers / delegate-or-continue). If that wake is delivered and the
task is *still* stranded, the ladder is exhausted → escalate to ``blocked`` + a
``missing_disposition`` recovery (spec 02 §5/§6).

The state is fully ledger-derived (no extra bookkeeping): a *pending* finish-handoff wake is
itself a live path, so :func:`~chorus.lifecycle.classify` reports the task healthy and a second
pass is a no-op — exactly-once nagging falls out for free. Only once that wake is *done* and the
task is stranded again does the reconciler escalate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from chorus.ids import mint_id
from chorus.ledger._models import (
    ActivityVerb,
    RecoveryAction,
    RecoveryKind,
    RunStatus,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
    WakeStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.lifecycle._liveness import classify

# The disposition the employee must declare on a finish-handoff (spec 02 §5).
_HANDOFF_CHOICES: tuple[str, ...] = ("done", "cancelled", "in_review", "blocked", "delegate")

if TYPE_CHECKING:
    from chorus.ledger import Ledger


class DispositionAction(StrEnum):
    """What :func:`reconcile_disposition` did (spec 02 §5)."""

    NOOP = "noop"
    HANDOFF_ENQUEUED = "handoff_enqueued"
    ESCALATED = "escalated"


@dataclass(frozen=True)
class Disposition:
    """The reconciler's verdict + the reason behind it (spec 02 §5)."""

    action: DispositionAction
    reason: str


def _handoff_key(task_id: str) -> str:
    return f"finish_handoff:{task_id}"


def reconcile_disposition(task: Task, ledger: Ledger, *, now: datetime) -> Disposition:
    """Reconcile a succeeded-but-undisposed task (spec 02 §5); see module docstring."""
    if task.status is not TaskStatus.IN_PROGRESS:
        return Disposition(DispositionAction.NOOP, "not_in_progress")
    if task.assignee_user_id is not None:
        return Disposition(DispositionAction.NOOP, "human_owner")
    if task.assignee_employee_id is None:
        return Disposition(DispositionAction.NOOP, "no_assignee")

    runs = ledger.runs.for_task(task.id)
    latest = runs[-1] if runs else None
    if latest is None or latest.status is not RunStatus.SUCCEEDED:
        # A crashed/continuing run is continuity recovery (§6), not a missing disposition.
        return Disposition(DispositionAction.NOOP, "no_successful_run")

    # A pending finish-handoff wake (or any other primitive) is a live path — don't nag again.
    live = classify(task, ledger, now=now)
    if live.healthy:
        return Disposition(DispositionAction.NOOP, f"has_live_path:{live.reason}")

    # Stranded after a success: enqueue one handoff, or escalate if a prior one was consumed.
    key = _handoff_key(task.id)
    delivered = any(w.status is WakeStatus.DONE for w in ledger.wakes.by_coalesce_key(key))
    if delivered:
        return _escalate(task, ledger)
    return _enqueue_handoff(task, ledger, key)


def _enqueue_handoff(task: Task, ledger: Ledger, key: str) -> Disposition:
    ledger.wakes.enqueue(
        Wake(
            id=mint_id(),
            employee_id=task.assignee_employee_id,  # type: ignore[arg-type]  # guarded above
            reason=WakeReason.RECOVERY,
            # carry the structured choice menu so the beat picks exactly one disposition (spec 02 §5)
            payload={
                "kind": "finish_handoff",
                "task_id": task.id,
                "choices": list(_HANDOFF_CHOICES),
            },
            coalesce_key=key,
        )
    )
    return Disposition(DispositionAction.HANDOFF_ENQUEUED, "finish_handoff")


def _escalate(task: Task, ledger: Ledger) -> Disposition:
    """Exhausted ladder: surface the stuck task as ``blocked`` + a recovery owner (spec 02 §5)."""
    action_id = mint_id()
    with ledger.transaction():
        ledger.tasks.transition(task.id, TaskStatus.BLOCKED)
        ledger.recovery_actions.open(
            RecoveryAction(
                id=action_id,
                source_task_id=task.id,
                kind=RecoveryKind.MISSING_DISPOSITION,
                owner_employee_id=task.assignee_employee_id,
                cause="missing_disposition",
                fingerprint="finish_handoff",
                next_action="declare a disposition: done/cancelled, in_review, blocked, or delegate",
            )
        )
        record_activity(
            ledger,
            verb=ActivityVerb.RECOVERED,
            subject_id=task.id,
            actor_employee_id=task.assignee_employee_id,
            payload={"cause": "missing_disposition", "recovery_action": action_id},
        )
    return Disposition(DispositionAction.ESCALATED, "missing_disposition")


__all__ = [
    "Disposition",
    "DispositionAction",
    "reconcile_disposition",
]
