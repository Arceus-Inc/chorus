"""revisit_sweep — reopen decisions whose revisit window has elapsed (pm design doc §13).

A deterministic maintenance scan, no model in the loop: it walks the decision log and, for each live
decision older than the revisit window, submits a fresh problem task assigned to the decision's original
owner so the discovery loop re-examines it ("did the metric move?"). It **proposes** — the reopened
problem is a normal, DoD-gated beat; the sweep never re-decides anything itself.

Idempotent: the reopen task's id is derived from the decision id, so a decision reopens at most once no
matter how often the sweep runs. Superseded decisions (a successor already re-decided them) and decisions
whose owner is gone are skipped. Role-agnostic — it reads ledger decision rows, not any employee package.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from chorus.ids import mint_id
from chorus.ledger._models import OriginKind, Task, TaskStatus, Wake, WakeReason

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger
    from chorus.ledger._models import DecisionRecord

# A decision is revisited two weeks after it was recorded, unless the caller overrides the window.
DEFAULT_REVISIT_WINDOW = timedelta(days=14)

_REVISIT_TASK_PREFIX = "revisit-"


def revisit_sweep(
    ledger: SqliteLedger, *, now: datetime, window: timedelta = DEFAULT_REVISIT_WINDOW
) -> list[str]:
    """Reopen every decision past its revisit window; return the reopened task ids (oldest first).

    A decision is due when it is live (not superseded) and was recorded on or before ``now - window``.
    Reopening submits a ``todo`` problem task assigned to the decision's original owner and wakes them;
    a decision already reopened, or whose owner no longer exists, is skipped.
    """
    reopened: list[str] = []
    for decision in ledger.decisions.due_for_revisit(before=now - window):
        task_id = f"{_REVISIT_TASK_PREFIX}{decision.id}"
        if ledger.tasks.get(task_id) is not None:
            continue  # already reopened — idempotent across sweeps
        origin = ledger.tasks.get(decision.task_id)
        owner = origin.assignee_employee_id if origin is not None else None
        if owner is None:
            continue  # no one to hand the reopened problem to
        with ledger.transaction():
            ledger.tasks.submit(
                Task(
                    id=task_id,
                    intent=_revisit_intent(decision),
                    status=TaskStatus.TODO,
                    assignee_employee_id=owner,
                    origin_kind=OriginKind.ROUTINE_EXECUTION,
                    origin_id=decision.id,
                    origin_fingerprint=task_id,
                )
            )
            ledger.wakes.enqueue(
                Wake(
                    id=mint_id("wake"),
                    employee_id=owner,
                    reason=WakeReason.CRON_DUE,
                    payload={"task_id": task_id},
                )
            )
        reopened.append(task_id)
    return reopened


def _revisit_intent(decision: DecisionRecord) -> str:
    """The reopened problem: re-examine the recorded decision against its own revisit trigger."""
    return (
        f"Revisit decision {decision.id}: we chose {decision.option!r}. "
        f"Did the outcome metric move — {decision.outcome_metric} — and does the revisit trigger hold: "
        f"{decision.revisit_trigger}? Gather fresh evidence and record a decision: confirm the original "
        f"(record it again with updated confidence) or supersede it with a new bet."
    )


__all__ = ["DEFAULT_REVISIT_WINDOW", "revisit_sweep"]
