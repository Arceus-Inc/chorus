"""revise_dod — the typed, audited DoD revision path (§1 DoD revisability, spec 04 §1).

A task's Definition-of-Done is mutable only here: the assignee's **manager** may raise the bar (a
**tighten**) immediately, but lowering it (a **loosen**) is staged and gated behind a §5 approval — a
worker can never weaken the gate that verifies its own work. Revisions never re-judge an already-run
evaluator; they take effect on the next disposition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from chorus.ledger._models import ActivityVerb, ApprovalAction, ApprovalSubjectKind
from chorus.lifecycle._audit import record_activity
from chorus.outcomes import RevisionDirection, Verifier, classify

if TYPE_CHECKING:
    from chorus.ledger import Ledger


class RevisionAuthorityError(RuntimeError):
    """The reviser is not the assignee's manager — only a manager may revise a DoD (spec 04 §1)."""


class NoRevision(RuntimeError):
    """There is nothing to revise — the task has no DoD, or the new verifier is identical."""


@dataclass(frozen=True)
class ReviseOutcome:
    """What a revision did (spec 04 §1)."""

    direction: RevisionDirection
    applied: bool  # True = in force now (tighten); False = staged behind a §5 gate (loosen)
    approval_id: str | None = None  # the loosen_dod gate, when one was opened (Slice 4)


def revise_dod(
    ledger: Ledger, *, task_id: str, new_verifier: Verifier, revised_by: str
) -> ReviseOutcome:
    """Revise ``task_id``'s DoD: a manager tighten applies now; a loosen is staged (gated in Slice 4)."""
    old = ledger.dod.verifier_for_task(task_id)
    if old is None:
        raise NoRevision(f"task {task_id!r} has no DoD to revise")
    _require_manager_authority(ledger, task_id, revised_by)

    direction = classify(old, new_verifier)
    if direction is RevisionDirection.NO_CHANGE:
        raise NoRevision(f"the proposed DoD for task {task_id!r} is identical — nothing to revise")
    if direction is RevisionDirection.TIGHTEN:
        ledger.dod.apply_revision(task_id, new_verifier)
        record_activity(
            ledger,
            verb=ActivityVerb.DOD_REVISED,
            subject_id=task_id,
            actor_employee_id=revised_by,
            payload={"direction": direction.value},
        )
        return ReviseOutcome(direction, applied=True)

    # LOOSEN — stage the proposal and open a §5 loosen_dod gate; the old (stricter) DoD stays in force
    # until a human approves (a worker can never weaken its own gate unilaterally).
    from chorus.governance import (
        GovernanceResolver,  # local import avoids a lifecycle↔governance cycle
    )

    ledger.dod.propose_revision(task_id, new_verifier)
    approval = GovernanceResolver(ledger).open(
        action=ApprovalAction.LOOSEN_DOD,
        subject_kind=ApprovalSubjectKind.TASK,
        subject_id=task_id,
        reason=f"loosen the DoD for task {task_id}",
    )
    record_activity(
        ledger,
        verb=ActivityVerb.DOD_REVISED,
        subject_id=task_id,
        actor_employee_id=revised_by,
        payload={"direction": direction.value, "gate": approval.id},
    )
    return ReviseOutcome(direction, applied=False, approval_id=approval.id)


def _require_manager_authority(ledger: Ledger, task_id: str, revised_by: str) -> None:
    task = ledger.tasks.get(task_id)
    assignee_id = task.assignee_employee_id if task is not None else None
    if assignee_id is None:
        raise RevisionAuthorityError(
            f"task {task_id!r} is unassigned — no manager to authorize a revision"
        )
    assignee = ledger.employees.get(assignee_id)
    manager_id = assignee.reports_to if assignee is not None else None
    if manager_id is None or revised_by != manager_id:
        raise RevisionAuthorityError(
            f"{revised_by!r} is not the manager of task {task_id!r} (only {manager_id!r} may revise)"
        )


__all__ = ["NoRevision", "ReviseOutcome", "RevisionAuthorityError", "revise_dod"]
