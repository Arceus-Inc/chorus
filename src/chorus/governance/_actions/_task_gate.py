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
    Run,
    RunStatus,
    TaskStatus,
    Wake,
    WakeReason,
)
from chorus.lifecycle._delegation_resolution import (
    DelegationResolutionError,
    DelegationResolutionPolicy,
)
from chorus.outcomes import DoDKind, pr_landing_of

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
            latest = self._ledger.artifacts.latest_primary_non_verdict(approval.subject_id)
            if (
                latest is not None
                and pr_landing_of(latest.type.value, latest.resource_ref).blocks_done
            ):
                raise TaskGateError(
                    f"acceptance gate {approval.id!r} cannot finalize an unmerged primary PR"
                )
            try:
                DelegationResolutionPolicy(self._ledger).ensure_approvable(approval.subject_id)
            except DelegationResolutionError as exc:
                raise TaskGateError(str(exc)) from exc
            if _is_strict_acceptance(self._ledger, approval.subject_id):
                producer_run = _latest_succeeded_task_run(self._ledger, approval.subject_id)
                if producer_run is None:
                    raise TaskGateError(
                        f"acceptance gate {approval.id!r} has no succeeded producer run"
                    )
                artifact = self._ledger.artifacts.mark_latest_pending_primary_non_verdict_verified(
                    approval.subject_id
                )
                if artifact is None:
                    raise TaskGateError(
                        f"acceptance gate {approval.id!r} has no pending primary non-verdict artifact to verify"
                    )
                latest_after = self._ledger.artifacts.latest_primary_non_verdict(
                    approval.subject_id
                )
                if latest_after is None or latest_after.id != artifact.id:
                    raise TaskGateError(
                        f"acceptance gate {approval.id!r} stamped a stale primary; "
                        "newest landing no longer matches the CAS row"
                    )
                wakes = self._ledger.finalize_beat(
                    task_id=approval.subject_id,
                    run_id=producer_run.id,
                    dod_status=DodStatus.PASSED,
                )
                try:
                    DelegationResolutionPolicy(self._ledger).approve(approval.subject_id)
                except DelegationResolutionError as exc:
                    raise TaskGateError(str(exc)) from exc
                return ActionOutcome(TaskStatus.DONE.value, len(wakes))
            wakes = self._ledger.finalize_beat(
                task_id=approval.subject_id,
                run_id=None,
                dod_status=DodStatus.PASSED,
            )
            try:
                DelegationResolutionPolicy(self._ledger).approve(approval.subject_id)
            except DelegationResolutionError as exc:
                raise TaskGateError(str(exc)) from exc
            return ActionOutcome(TaskStatus.DONE.value, len(wakes))
        self._ledger.tasks.transition(approval.subject_id, TaskStatus.TODO)
        return ActionOutcome(TaskStatus.TODO.value, self._wake_assignee(approval.subject_id))

    def on_deny(self, approval: Approval) -> ActionOutcome:
        gate = _require_gate(approval)
        if gate is ApprovalGate.ACCEPTANCE:
            dod = self._ledger.dod.get_for_task(approval.subject_id)
            if dod is not None:
                self._ledger.dod.record_verdict(dod.id, DodStatus.FAILED)
            DelegationResolutionPolicy(self._ledger).deny(approval.subject_id)
            return ActionOutcome(TaskStatus.BLOCKED.value)
        self._ledger.tasks.transition(approval.subject_id, TaskStatus.CANCELLED)
        return ActionOutcome(TaskStatus.CANCELLED.value)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        gate = _require_gate(approval)
        if gate is ApprovalGate.ACCEPTANCE:
            dod = self._ledger.dod.get_for_task(approval.subject_id)
            if dod is not None:
                self._ledger.dod.record_verdict(dod.id, DodStatus.FAILED)
        self._ledger.tasks.set_status(approval.subject_id, TaskStatus.TODO)
        DelegationResolutionPolicy(self._ledger).request_revision(approval.subject_id)
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


def _latest_succeeded_task_run(ledger: Ledger, task_id: str) -> Run | None:
    for run in reversed(ledger.runs.for_task(task_id)):
        if run.status is RunStatus.SUCCEEDED:
            return run
    return None


def _is_strict_acceptance(ledger: Ledger, task_id: str) -> bool:
    dod = ledger.dod.get_for_task(task_id)
    if dod is not None and dod.kind == DoDKind.HUMAN_APPROVAL.value:
        return True
    return ledger.artifacts.has_pending_primary_non_verdict(task_id)


__all__ = ["TaskGateAction", "TaskGateError"]
