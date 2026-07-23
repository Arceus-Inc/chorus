"""The board-approval governed action (§5 governance).

Gates promotion of a landed deliverable artifact to the board / external. The gate's subject is the
artifact id:

- approve → record a ``promoted`` activity on the artifact; the deliverable is on the board.
- deny    → no promotion (the resolver's audit records the denial).
- revise  → wake the artifact's source-task assignee to revise the deliverable.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.governance._types import ActionOutcome
from chorus.ids import mint_id
from chorus.ledger import Activity, ActivityVerb, Approval, ApprovalAction, Wake, WakeReason

if TYPE_CHECKING:
    from chorus.ledger import Ledger

_PROMOTED = "promoted"
_DENIED = "denied"
_REVISION = "revision"


class BoardApprovalAction:
    """The ``board_approval`` handler — promote, reject, or send back a deliverable artifact."""

    action = ApprovalAction.BOARD_APPROVAL

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def on_open(self, approval: Approval) -> None:
        return None  # the resolver audits the GATED event on the artifact

    def on_approve(self, approval: Approval) -> ActionOutcome:
        self._ledger.activity.append(
            Activity(
                id=mint_id(),
                verb=ActivityVerb.PROMOTED,
                subject_kind="artifact",
                subject_id=approval.subject_id,
                actor_user_id=approval.decided_by_user_id,
            )
        )
        return ActionOutcome(_PROMOTED)

    def on_deny(self, approval: Approval) -> ActionOutcome:
        return ActionOutcome(_DENIED)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        artifact = self._ledger.artifacts.get(approval.subject_id)
        task = self._ledger.tasks.get(artifact.task_id) if artifact is not None else None
        author_id = task.assignee_employee_id if task is not None else None
        woken = self._wake_author(author_id, artifact.task_id if artifact is not None else "")
        return ActionOutcome(_REVISION, woken)

    def _wake_author(self, employee_id: str | None, task_id: str) -> int:
        if employee_id is None:
            return 0
        self._ledger.wakes.enqueue(
            Wake(
                id=mint_id(),
                employee_id=employee_id,
                reason=WakeReason.RECOVERY,
                payload={"task_id": task_id},
            )
        )
        return 1


__all__ = ["BoardApprovalAction"]
