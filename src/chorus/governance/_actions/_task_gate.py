"""The task-gate governed action — acceptance / authorization (§5 governance).

The original task gate, lifted from the resolver into a handler so it is one action among many. A
task needing sign-off sits ``blocked``; resolving acts on it per its :class:`ApprovalGate`:

- **acceptance** — the approval *is* the task's acceptance: approve → ``done``; deny → DoD ``failed``,
  stays ``blocked``.
- **authorization** — the approval *authorises the work*: approve → ``todo`` + wake the assignee;
  deny → ``cancelled``.

``revise`` sends the work back: ``todo`` + a recovery wake to the assignee.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.governance._errors import GovernanceError
from chorus.governance._types import ActionOutcome
from chorus.ids import mint_id
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    DodStatus,
    TaskStatus,
    Wake,
    WakeReason,
)

if TYPE_CHECKING:
    from chorus.ledger import Ledger


class TaskGateError(GovernanceError):
    """A task gate with no ``gate_kind`` — it cannot act on its task."""


class TaskGateAction:
    """The ``task_gate`` handler (acceptance / authorization), owned by the governance registry."""

    action = ApprovalAction.TASK_GATE

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def on_open(self, approval: Approval) -> None:
        self._ledger.tasks.set_status(approval.subject_id, TaskStatus.BLOCKED)

    def on_approve(self, approval: Approval) -> ActionOutcome:
        gate = _require_gate(approval)
        if gate is ApprovalGate.ACCEPTANCE:
            wakes = self._ledger.finalize_beat(
                task_id=approval.subject_id, run_id=None, dod_status=DodStatus.PASSED
            )
            return ActionOutcome(TaskStatus.DONE.value, len(wakes))
        self._ledger.tasks.transition(approval.subject_id, TaskStatus.TODO)
        return ActionOutcome(TaskStatus.TODO.value, self._wake_assignee(approval.subject_id))

    def on_deny(self, approval: Approval) -> ActionOutcome:
        gate = _require_gate(approval)
        if gate is ApprovalGate.ACCEPTANCE:
            dod = self._ledger.dod.get_for_task(approval.subject_id)
            if dod is not None:
                self._ledger.dod.record_verdict(dod.id, DodStatus.FAILED)
            return ActionOutcome(TaskStatus.BLOCKED.value)
        self._ledger.tasks.transition(approval.subject_id, TaskStatus.CANCELLED)
        return ActionOutcome(TaskStatus.CANCELLED.value)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        _require_gate(approval)  # only a task gate is revisable here
        self._ledger.tasks.set_status(approval.subject_id, TaskStatus.TODO)
        return ActionOutcome(TaskStatus.TODO.value, self._wake_assignee(approval.subject_id))

    def _wake_assignee(self, task_id: str) -> int:
        task = self._ledger.tasks.get(task_id)
        if task is None or task.assignee_employee_id is None:
            return 0
        self._ledger.wakes.enqueue(
            Wake(
                id=mint_id(),
                employee_id=task.assignee_employee_id,
                reason=WakeReason.TASK_ASSIGNED,
                payload={"task_id": task_id},
            )
        )
        return 1


def _require_gate(approval: Approval) -> ApprovalGate:
    if approval.gate_kind is None:
        raise TaskGateError(f"task gate {approval.id!r} has no gate_kind")
    return approval.gate_kind


__all__ = ["TaskGateAction", "TaskGateError"]
