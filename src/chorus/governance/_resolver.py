"""The governance resolver — a thin, atomic, audited dispatcher (spec 04 §5, Approach A).

An ``approval`` is the governed-action queue: opening one parks/flags its subject, resolving it
*performs the org mutation*. This resolver owns neither the open- nor the resolve-side effect — it
opens a transaction, stamps the approval, audits it, and delegates the mutation to the
:class:`GovernedAction` handler registered for the approval's :class:`ApprovalAction`. Adding an
action is one handler in :func:`~chorus.governance.default_actions`, never an edit here.

``open_task_gate`` stays as the task-gate convenience used by the ``human_approval`` DoD hook + CLI.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from chorus.governance._errors import GovernanceError
from chorus.governance._registry import GovernanceRegistry, default_actions
from chorus.governance._types import ActionOutcome, ApprovalDecision
from chorus.ledger import (
    Activity,
    ActivityVerb,
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    TaskStatus,
)

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})

_DECISION_VERB: dict[ApprovalDecision, ActivityVerb] = {
    ApprovalDecision.APPROVE: ActivityVerb.APPROVED,
    ApprovalDecision.DENY: ActivityVerb.DENIED,
    ApprovalDecision.REQUEST_REVISION: ActivityVerb.REVISION_REQUESTED,
}


@dataclass(frozen=True)
class ResolveOutcome:
    """What resolving an approval did — the decision and the gated subject's new status (spec 04 §5)."""

    approval_id: str
    subject_id: str
    decision: ApprovalStatus
    subject_status: str
    wakes_fired: int


class GovernanceResolver:
    """Open and resolve governed-action approvals over a ledger, dispatching to handlers (spec 04 §5)."""

    def __init__(self, ledger: SqliteLedger, registry: GovernanceRegistry | None = None) -> None:
        self._ledger = ledger
        self._registry = registry or GovernanceRegistry.from_actions(default_actions(ledger))

    # -- opening ----------------------------------------------------------------------------------

    def open(
        self,
        *,
        action: ApprovalAction,
        subject_kind: ApprovalSubjectKind,
        subject_id: str,
        reason: str,
        gate_kind: ApprovalGate | None = None,
    ) -> Approval:
        """Open a pending gate and let its handler park/flag the subject — atomic + audited.

        The exact-once index rejects a second open gate on the same subject (a duplicate raises)."""
        handler = self._registry.get(action)
        approval = Approval(
            id=_mint("ap"),
            subject_kind=subject_kind,
            subject_id=subject_id,
            reason=reason,
            action=action,
            gate_kind=gate_kind,
        )
        with self._ledger.transaction():
            opened = self._ledger.approvals.request(approval)
            handler.on_open(opened)
            self._audit(ActivityVerb.GATED, opened, actor=None)
        return opened

    def open_plan_gate(self, parent_id: str, *, reason: str) -> Approval:
        """Hold a freshly-decomposed parent's children ``blocked`` and open its plan-approval gate.

        Called right after a manager decomposes when ``policy.plan_gate_required`` — the children were
        created ``todo`` + assignment-waked, so each is demoted to ``blocked`` and its queued wake
        dropped, parking the plan until a human signs it off (approve releases them again)."""
        for child in self._ledger.tasks.children(parent_id):
            if child.status is TaskStatus.TODO:
                self._ledger.tasks.set_status(child.id, TaskStatus.BLOCKED)
                if child.assignee_employee_id is not None:
                    self._ledger.wakes.drop_queued(employee_id=child.assignee_employee_id)
        return self.open(
            action=ApprovalAction.PLAN_APPROVAL,
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=parent_id,
            reason=reason,
        )

    def open_task_gate(self, task_id: str, *, gate_kind: ApprovalGate, reason: str) -> Approval:
        """Open a task acceptance/authorization gate (the ``human_approval`` DoD hook + CLI path)."""
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise GovernanceError(f"no such task: {task_id!r}")
        if task.status in _TERMINAL:
            raise GovernanceError(f"task {task_id!r} is {task.status.value} (terminal)")
        return self.open(
            action=ApprovalAction.TASK_GATE,
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=task_id,
            reason=reason,
            gate_kind=gate_kind,
        )

    # -- resolving --------------------------------------------------------------------------------

    def resolve(
        self,
        approval_id: str,
        *,
        decision: ApprovalDecision,
        decided_by_user_id: str,
        now: datetime,
    ) -> ResolveOutcome:
        """Resolve a pending gate; its handler performs the org mutation — atomic + audited.

        Raises :class:`GovernanceError` for an unknown approval or one that is no longer pending."""
        del now  # stamping is the repo's job; kept for a stable governance-call signature
        approval = self._ledger.approvals.get(approval_id)
        if approval is None:
            raise GovernanceError(f"no such approval: {approval_id!r}")
        if approval.status is not ApprovalStatus.PENDING:
            raise GovernanceError(f"approval {approval_id!r} already {approval.status.value}")
        handler = self._registry.get(approval.action)
        apply: dict[ApprovalDecision, Callable[[Approval], ActionOutcome]] = {
            ApprovalDecision.APPROVE: handler.on_approve,
            ApprovalDecision.DENY: handler.on_deny,
            ApprovalDecision.REQUEST_REVISION: handler.on_revise,
        }
        with self._ledger.transaction():
            self._ledger.approvals.set_status(
                approval_id, decision.status, decided_by_user_id=decided_by_user_id
            )
            outcome = apply[decision](approval)
            self._audit(_DECISION_VERB[decision], approval, actor=decided_by_user_id)
        return ResolveOutcome(
            approval_id=approval_id,
            subject_id=approval.subject_id,
            decision=decision.status,
            subject_status=outcome.subject_status,
            wakes_fired=outcome.wakes_fired,
        )

    # -- audit ------------------------------------------------------------------------------------

    def _audit(self, verb: ActivityVerb, approval: Approval, *, actor: str | None) -> None:
        self._ledger.activity.append(
            Activity(
                id=_mint("act"),
                verb=verb,
                subject_kind=approval.subject_kind.value,
                subject_id=approval.subject_id,
                actor_user_id=actor,
            )
        )


def _mint(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


__all__ = ["GovernanceError", "GovernanceResolver", "ResolveOutcome"]
