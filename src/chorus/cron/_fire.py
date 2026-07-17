"""Firing a routine — a cron edge resolved into ledger writes, never an agent call (spec 03 §4).

``fire_routine`` is the tick's CRON step (§3b) made concrete: the double-fire-guarded edge advance
(``claim_fire``), the exact-once firing record (``routine_run.idempotency_key``), the
``skip_if_active`` gate, then either a spawned ``task`` (the normal path, exact-once via
``task_open_routine_uq``) or a ``next_beat`` note — and in both cases a ``cron_due`` wake the normal
dispatch loop drains. It writes rows and returns; it never invokes ``dream.run_task``.
"""

from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from chorus.cron._routine import parse_cron
from chorus.ids import mint_id
from chorus.ledger._models import (
    OriginKind,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRun,
    RoutineRunStatus,
    RoutineStatus,
    RoutineTarget,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)

if TYPE_CHECKING:
    from datetime import datetime

    from chorus.ledger import SqliteLedger
    from chorus.ledger._models import Routine, RoutineTrigger


def fire_routine(ledger: SqliteLedger, trigger: RoutineTrigger, *, now: datetime) -> str | None:
    """Resolve one due ``routine_trigger`` into ledger writes (spec 03 §4).

    Returns the spawned task id on the ``spawn_task`` path, else ``None`` (a ``next_beat`` note, a
    lost edge race, a duplicate firing, or a ``skip_if_active`` suppression). Ordered so exactly one
    caller can win: advance the edge first (``claim_fire``), then record the firing (the idempotency
    index is the belt to that suspenders), then gate on concurrency, then write the work.
    """
    if trigger.cron_expression is None or trigger.next_run_at is None:
        return None
    routine = ledger.routines.get(trigger.routine_id)
    if routine is None or routine.status is not RoutineStatus.ACTIVE:
        return None

    # Pin the live revision: the run records which definition it fired under and the spawned task's
    # intent is sourced from it, so an edit while this firing is in flight never re-judges it (§2.3).
    pinned_id = routine.latest_revision_id
    pinned = ledger.routine_revisions.get(pinned_id) if pinned_id is not None else None
    intent = pinned.intent_template if pinned is not None else routine.intent_template

    edge = trigger.next_run_at
    # Catch-up policy (spec 03 §4): skip_missed jumps the edge past ``now`` (dropping every window
    # missed while chorus was down); backfill_one advances a single cron step from the edge, so each
    # tick fires exactly one missed window until caught up — one-at-a-time, throttled to one task/tick.
    catch_up_base = edge if routine.catch_up_policy is RoutineCatchUp.BACKFILL_ONE else now
    next_edge = parse_cron(trigger.cron_expression, base=catch_up_base, timezone=trigger.timezone)
    # Double-fire guard (spec 03 §5): only the tick still holding this edge advances it and proceeds.
    if not ledger.routine_triggers.claim_fire(
        trigger.id, expected_next_run_at=edge, new_next_run_at=next_edge
    ):
        return None

    idempotency_key = f"{routine.id}:{trigger.id}:{edge.isoformat()}"
    run_id = mint_id()

    # Concurrency policy (spec 03 §4): while a prior task for this routine is still open,
    # ``skip_if_active`` suppresses the firing and ``coalesce`` folds it onto the live run (linking
    # the survivor); ``always`` ignores the open task and spawns a fresh one.
    if (
        routine.concurrency_policy is not RoutineConcurrency.ALWAYS
        and ledger.tasks.has_open_for_routine(routine.id)
    ):
        if routine.concurrency_policy is RoutineConcurrency.COALESCE:
            _record(
                ledger,
                run_id,
                routine,
                trigger,
                idempotency_key,
                RoutineRunStatus.COALESCED,
                routine_revision_id=pinned_id,
                coalesced_into_run_id=_latest_dispatched_run(ledger, routine.id),
            )
        else:  # skip_if_active
            _record(
                ledger,
                run_id,
                routine,
                trigger,
                idempotency_key,
                RoutineRunStatus.SUPPRESSED,
                routine_revision_id=pinned_id,
            )
        return None

    if (
        _record(ledger, run_id, routine, trigger, idempotency_key, routine_revision_id=pinned_id)
        is None
    ):
        return None  # a duplicate firing already landed this edge

    if routine.target is RoutineTarget.SPAWN_TASK:
        task_id = mint_id()
        ledger.tasks.submit(
            Task(
                id=task_id,
                intent=intent,
                status=TaskStatus.TODO,
                assignee_employee_id=routine.employee_id,
                goal_id=routine.goal_id,
                parent_id=routine.parent_task_id,
                origin_kind=OriginKind.ROUTINE_EXECUTION,
                origin_id=routine.id,
                origin_fingerprint=idempotency_key,
            )
        )
        ledger.routine_runs.dispatch(run_id, linked_task_id=task_id)
        ledger.wakes.enqueue(
            Wake(
                id=mint_id(),
                employee_id=routine.employee_id,
                reason=WakeReason.CRON_DUE,
                payload={"task_id": task_id},
            )
        )
        return task_id

    # next_beat — no new task, just extra context delivered on the employee's next beat.
    ledger.wakes.enqueue(
        Wake(
            id=mint_id(),
            employee_id=routine.employee_id,
            reason=WakeReason.CRON_DUE,
            payload={"note": intent},
        )
    )
    return None


def _record(
    ledger: SqliteLedger,
    run_id: str,
    routine: Routine,
    trigger: RoutineTrigger,
    idempotency_key: str,
    status: RoutineRunStatus = RoutineRunStatus.RECEIVED,
    *,
    routine_revision_id: str | None = None,
    coalesced_into_run_id: str | None = None,
) -> str | None:
    """Register the firing exact-once; ``None`` if the idempotency key already fired this edge."""
    try:
        ledger.routine_runs.record(
            RoutineRun(
                id=run_id,
                routine_id=routine.id,
                trigger_id=trigger.id,
                status=status,
                idempotency_key=idempotency_key,
                routine_revision_id=routine_revision_id,
                coalesced_into_run_id=coalesced_into_run_id,
            )
        )
    except sqlite3.IntegrityError:
        return None
    return run_id


def _latest_dispatched_run(ledger: SqliteLedger, routine_id: str) -> str | None:
    """The most recent *dispatched* run for the routine — the survivor a coalesced firing folds into."""
    dispatched = [
        run
        for run in ledger.routine_runs.by_routine(routine_id)
        if run.status is RoutineRunStatus.DISPATCHED
    ]
    return dispatched[-1].id if dispatched else None


__all__ = ["fire_routine"]
