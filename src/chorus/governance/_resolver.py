"""The governance resolver — resolving an approval performs the org mutation (spec 04 §5).

An ``approval`` is the governed-action queue: opening one parks its subject, resolving it (approve /
deny) *acts* on the subject. This resolver owns the **task gate** — the governed action wired today —
in the two flavours the approval carries (:class:`~chorus.ledger.ApprovalGate`):

- **acceptance** — the approval *is* the task's acceptance: approve → ``done`` (+ downstream wakes),
  deny → stays ``blocked`` with the DoD recorded ``failed``.
- **authorization** — the approval *authorises the work to proceed*: approve → ``todo`` (+ a wake to
  the assignee), deny → ``cancelled``.

Every resolution is atomic (one ledger transaction) and audited. Budget-incident approvals stay with
the §3 enforcer; this resolver rejects non-task subjects rather than guessing.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from chorus.ledger import (
    Activity,
    ActivityVerb,
    Approval,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    DodStatus,
    TaskStatus,
    Wake,
    WakeReason,
)

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})


class GovernanceError(RuntimeError):
    """A resolution that cannot proceed — unknown / already-decided approval, or an unsupported gate."""


@dataclass(frozen=True)
class ResolveOutcome:
    """What resolving an approval did — the decision and where it left the task (spec 04 §5)."""

    approval_id: str
    task_id: str
    decision: ApprovalStatus
    task_status: TaskStatus
    wakes_fired: int


class GovernanceResolver:
    """Open and resolve task-gating approvals over a ledger (spec 04 §5)."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    # -- opening ----------------------------------------------------------------------------------

    def open_task_gate(self, task_id: str, *, gate_kind: ApprovalGate, reason: str) -> Approval:
        """Open a pending gate on a task and park it ``blocked`` — atomic + audited.

        Raises :class:`GovernanceError` if the task is unknown or terminal; the exact-once index
        rejects a second open gate on the same task (a duplicate ``request`` raises).
        """
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise GovernanceError(f"no such task: {task_id!r}")
        if task.status in _TERMINAL:
            raise GovernanceError(f"task {task_id!r} is {task.status.value} (terminal)")
        approval = Approval(
            id=_mint("ap"),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=task_id,
            reason=reason,
            gate_kind=gate_kind,
        )
        with self._ledger.transaction():
            opened = self._ledger.approvals.request(approval)
            self._ledger.tasks.set_status(task_id, TaskStatus.BLOCKED)
            self._audit(ActivityVerb.GATED, task_id, actor=None)
        return opened

    # -- resolving --------------------------------------------------------------------------------

    def resolve(
        self, approval_id: str, *, approve: bool, decided_by_user_id: str, now: datetime
    ) -> ResolveOutcome:
        """Resolve a pending task gate; the task moves per its gate kind — atomic + audited.

        Raises :class:`GovernanceError` for an unknown approval, one that is no longer pending, a
        non-task subject, or a task gate with no ``gate_kind``.
        """
        del now  # stamping is the repo's job; kept for a stable governance-call signature
        approval = self._ledger.approvals.get(approval_id)
        if approval is None:
            raise GovernanceError(f"no such approval: {approval_id!r}")
        if approval.status is not ApprovalStatus.PENDING:
            raise GovernanceError(f"approval {approval_id!r} already {approval.status.value}")
        if approval.subject_kind is not ApprovalSubjectKind.TASK:
            raise GovernanceError(
                f"resolver handles task gates only, not {approval.subject_kind.value}"
            )
        decision = ApprovalStatus.APPROVED if approve else ApprovalStatus.DENIED
        with self._ledger.transaction():
            if approve:
                self._ledger.approvals.approve(approval_id, decided_by_user_id=decided_by_user_id)
            else:
                self._ledger.approvals.deny(approval_id, decided_by_user_id=decided_by_user_id)
            status, wakes_fired = self._apply_task(approval, approve=approve)
            self._audit(
                ActivityVerb.APPROVED if approve else ActivityVerb.DENIED,
                approval.subject_id,
                actor=decided_by_user_id,
            )
        return ResolveOutcome(
            approval_id=approval_id,
            task_id=approval.subject_id,
            decision=decision,
            task_status=status,
            wakes_fired=wakes_fired,
        )

    # -- the task side-effect ---------------------------------------------------------------------

    def _apply_task(self, approval: Approval, *, approve: bool) -> tuple[TaskStatus, int]:
        task_id = approval.subject_id
        gate = approval.gate_kind
        if gate is ApprovalGate.ACCEPTANCE:
            if approve:
                wakes = self._ledger.finalize_beat(
                    task_id=task_id, run_id=None, dod_status=DodStatus.PASSED
                )
                return TaskStatus.DONE, len(wakes)
            dod = self._ledger.dod.get_for_task(task_id)
            if dod is not None:
                self._ledger.dod.record_verdict(dod.id, DodStatus.FAILED)
            return TaskStatus.BLOCKED, 0
        if gate is ApprovalGate.AUTHORIZATION:
            if approve:
                self._ledger.tasks.transition(task_id, TaskStatus.TODO)
                return TaskStatus.TODO, self._wake_assignee(task_id)
            self._ledger.tasks.transition(task_id, TaskStatus.CANCELLED)
            return TaskStatus.CANCELLED, 0
        raise GovernanceError(f"task gate {approval.id!r} has no gate_kind")

    def _wake_assignee(self, task_id: str) -> int:
        task = self._ledger.tasks.get(task_id)
        if task is None or task.assignee_employee_id is None:
            return 0
        self._ledger.wakes.enqueue(
            Wake(
                id=_mint("wake"),
                employee_id=task.assignee_employee_id,
                reason=WakeReason.TASK_ASSIGNED,
                payload={"task_id": task_id},
            )
        )
        return 1

    def _audit(self, verb: ActivityVerb, task_id: str, *, actor: str | None) -> None:
        self._ledger.activity.append(
            Activity(
                id=_mint("act"),
                verb=verb,
                subject_kind="task",
                subject_id=task_id,
                actor_user_id=actor,
            )
        )


def _mint(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


__all__ = ["GovernanceError", "GovernanceResolver", "ResolveOutcome"]
