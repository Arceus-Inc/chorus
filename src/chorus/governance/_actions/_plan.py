"""The plan-approval governed action (§5 governance).

A manager decomposed a parent into children that were held ``blocked`` pending sign-off (the
decompose-with-gate path). This gate signs off the *plan*:

- approve  → release every held child to ``todo`` + wake its assignee; the plan proceeds.
- deny     → cancel every held child; the parent is ``blocked`` with a recovery card (a human owns it).
- revise   → cancel every held child; the parent returns to ``todo`` with a recovery wake to the
             manager so it re-plans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.governance._types import ActionOutcome
from chorus.ids import mint_id
from chorus.ledger import (
    Approval,
    ApprovalAction,
    RecoveryAction,
    RecoveryKind,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


class PlanApprovalAction:
    """The ``plan_approval`` handler — release, cancel, or send back a manager's decomposed plan."""

    action = ApprovalAction.PLAN_APPROVAL

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def on_open(self, approval: Approval) -> None:
        return None  # the children are already held blocked by the decompose-with-gate

    def on_approve(self, approval: Approval) -> ActionOutcome:
        woken = 0
        for child in self._held_children(approval.subject_id):
            self._ledger.tasks.set_status(child.id, TaskStatus.TODO)
            woken += self._wake(child.assignee_employee_id, child.id, WakeReason.TASK_ASSIGNED)
        return ActionOutcome(TaskStatus.TODO.value, woken)

    def on_deny(self, approval: Approval) -> ActionOutcome:
        self._cancel_held_children(approval.subject_id)
        self._ledger.tasks.set_status(approval.subject_id, TaskStatus.BLOCKED)
        self._open_recovery(approval.subject_id)
        return ActionOutcome(TaskStatus.BLOCKED.value)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        self._cancel_held_children(approval.subject_id)
        parent = self._ledger.tasks.get(approval.subject_id)
        self._ledger.tasks.set_status(approval.subject_id, TaskStatus.TODO)
        manager_id = parent.assignee_employee_id if parent is not None else None
        woken = self._wake(manager_id, approval.subject_id, WakeReason.RECOVERY)
        return ActionOutcome(TaskStatus.TODO.value, woken)

    # -- helpers ----------------------------------------------------------------------------------

    def _held_children(self, parent_id: str) -> list[Task]:
        return [c for c in self._ledger.tasks.children(parent_id) if c.status is TaskStatus.BLOCKED]

    def _cancel_held_children(self, parent_id: str) -> None:
        for child in self._held_children(parent_id):
            self._ledger.tasks.set_status(child.id, TaskStatus.CANCELLED)

    def _wake(self, employee_id: str | None, task_id: str, reason: WakeReason) -> int:
        if employee_id is None:
            return 0
        self._ledger.wakes.enqueue(
            Wake(
                id=mint_id("wake"),
                employee_id=employee_id,
                reason=reason,
                payload={"task_id": task_id},
            )
        )
        return 1

    def _open_recovery(self, parent_id: str) -> None:
        if self._ledger.recovery_actions.active_for_source(parent_id) is not None:
            return
        parent = self._ledger.tasks.get(parent_id)
        self._ledger.recovery_actions.open(
            RecoveryAction(
                id=mint_id("rec"),
                source_task_id=parent_id,
                kind=RecoveryKind.STRANDED,
                owner_employee_id=parent.assignee_employee_id if parent is not None else None,
                cause="plan_denied",
                fingerprint="plan_approval",
                next_action="revise or re-decompose the rejected plan",
            )
        )


__all__ = ["PlanApprovalAction"]
