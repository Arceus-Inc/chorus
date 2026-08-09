"""The shared event choke for scheduler and governed terminal outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from chorus.events import Event, EventKind
from chorus.heartbeat._beat import BeatOutcome
from chorus.heartbeat._landed_outcome import DerivedLandedOutcome, derive_landed_outcome
from chorus.ledger import (
    ApprovalGate,
    ApprovalStatus,
    DodStatus,
    ExecutionMode,
    IntegrationVerdict,
    TaskStatus,
)
from chorus.observability._trace import trace_root
from chorus.outcomes import DoDKind

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Task
    from chorus.observability import EventSink


def emit_landed_outcome(
    ledger: Ledger,
    sink: EventSink | None,
    *,
    task: Task,
    result: BeatOutcome,
    at: datetime,
    employee_id: str | None,
    run_id: str | None,
    orchestrated: bool | None = None,
) -> DerivedLandedOutcome | None:
    """Emit one event from durable state, suppressing pending human acceptance."""
    if sink is None:
        return None
    latest = ledger.tasks.get(task.id) or task
    dod_row = ledger.dod.get_for_task(task.id)
    if dod_row is not None and dod_row.status is DodStatus.PENDING:
        verifier = ledger.dod.verifier_for_task(task.id)
        if verifier is not None and verifier.kind is DoDKind.HUMAN_APPROVAL:
            pending_acceptance = any(
                approval.status is ApprovalStatus.PENDING
                and approval.gate_kind is ApprovalGate.ACCEPTANCE
                for approval in ledger.approvals.for_subject(task.id)
            )
            if pending_acceptance:
                return None
    dod_status = dod_row.status if dod_row is not None else None
    integration = dod_row.integration_verdict if dod_row is not None else IntegrationVerdict()
    if orchestrated is None:
        orchestrated = (
            latest.execution_mode is ExecutionMode.DELEGATION
            and latest.status is TaskStatus.BLOCKED
            and ledger.tasks.has_children(task.id)
        )
    try:
        landed = derive_landed_outcome(
            latest,
            result,
            dod_status,
            orchestrated=orchestrated,
            integration=integration,
        )
    except ValueError:
        return None
    emit_derived_landed_outcome(
        ledger,
        sink,
        task=task,
        landed=landed,
        at=at,
        employee_id=employee_id,
        run_id=run_id,
    )
    return landed


def emit_derived_landed_outcome(
    ledger: Ledger,
    sink: EventSink | None,
    *,
    task: Task,
    landed: DerivedLandedOutcome,
    at: datetime,
    employee_id: str | None,
    run_id: str | None,
) -> bool:
    """Project an already-derived durable landed receipt onto the live event stream."""
    if sink is None:
        return False
    sink.emit(
        Event(
            kind=EventKind.OUTCOME_LANDED,
            at=at,
            trace_id=trace_root(ledger, task.id),
            task_id=task.id,
            employee_id=employee_id,
            run_id=run_id,
            payload={
                **landed.to_dict(),
                "passed": landed.strategy_passed(),
                "recovery_hint": landed.recovery_hint().value,
            },
        )
    )
    return True


__all__ = ["emit_derived_landed_outcome", "emit_landed_outcome"]
