"""The shared event choke for scheduler and governed terminal outcomes."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from chorus.events import Event, EventKind
from chorus.heartbeat._landed_outcome import DerivedLandedOutcome
from chorus.observability._trace import trace_root

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Task
    from chorus.observability import EventSink


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


__all__ = ["emit_derived_landed_outcome"]
