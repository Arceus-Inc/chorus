"""Cron firing — a due routine resolved into ledger writes, never an agent call (spec 03 §4).

``parse_cron`` is the thin adapter over dream's 5-field parser; ``fire_routine`` is the tick's CRON
step: advance the edge (double-fire-guarded), record the firing exact-once, gate on ``skip_if_active``,
then spawn a task (+ ``cron_due`` wake) or drop a ``next_beat`` note. These tests drive the firing
directly (the tick wiring is exercised in the heartbeat suite).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from chorus.cron._fire import fire_routine
from chorus.cron._routine import parse_cron
from chorus.ledger import SqliteLedger
from chorus.ledger._models import (
    OriginKind,
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRunStatus,
    RoutineStatus,
    RoutineTarget,
    RoutineTrigger,
    TaskStatus,
    WakeReason,
    WakeStatus,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


def _routine(
    ledger: SqliteLedger,
    *,
    rid: str = "r1",
    eid: str = "e1",
    target: RoutineTarget = RoutineTarget.SPAWN_TASK,
    concurrency: RoutineConcurrency = RoutineConcurrency.SKIP_IF_ACTIVE,
    catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED,
    cron: str = "0 * * * *",
) -> RoutineTrigger:
    """An active routine + its due cron trigger, returned ready to fire."""
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.routines.create(
        Routine(
            id=rid,
            employee_id=eid,
            intent_template=f"hourly sweep {rid}",
            target=target,
            concurrency_policy=concurrency,
            catch_up_policy=catch_up,
        )
    )
    return ledger.routine_triggers.create(
        RoutineTrigger(
            id=f"trig_{rid}",
            routine_id=rid,
            cron_expression=cron,
            next_run_at=_NOW,  # due now
        )
    )


def test_parse_cron_returns_next_edge_after_base() -> None:
    nxt = parse_cron("0 * * * *", base=_NOW)
    assert nxt > _NOW
    assert nxt == _NOW + timedelta(hours=1)


def test_fire_spawns_a_task_assigned_to_the_routine_owner(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    task_id = fire_routine(ledger, trig, now=_NOW)
    assert task_id is not None
    task = ledger.tasks.get(task_id)
    assert task is not None
    assert task.assignee_employee_id == "e1"
    assert task.status is TaskStatus.TODO
    assert task.origin_kind is OriginKind.ROUTINE_EXECUTION
    assert task.origin_id == "r1"


def test_fire_stamps_the_routine_execution_origin_fingerprint(ledger: SqliteLedger) -> None:
    # S0 regression floor: the spawned task carries the firing's idempotency key as its
    # origin fingerprint, so "this task came from routine r1, this exact edge" is durable.
    trig = _routine(ledger)
    task_id = fire_routine(ledger, trig, now=_NOW)
    assert task_id is not None
    task = ledger.tasks.get(task_id)
    assert task is not None
    run = ledger.routine_runs.by_routine("r1")[0]
    assert task.origin_kind is OriginKind.ROUTINE_EXECUTION
    assert task.origin_id == "r1"
    assert task.origin_fingerprint == run.idempotency_key
    assert task.origin_fingerprint == f"r1:{trig.id}:{_NOW.isoformat()}"


def test_fire_enqueues_a_cron_due_wake(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    task_id = fire_routine(ledger, trig, now=_NOW)
    queued = ledger.wakes.queued(employee_id="e1")
    assert len(queued) == 1
    assert queued[0].reason is WakeReason.CRON_DUE
    assert queued[0].payload["task_id"] == task_id


def test_fire_advances_the_trigger_edge(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    fire_routine(ledger, trig, now=_NOW)
    advanced = ledger.routine_triggers.get(trig.id)
    assert advanced is not None
    assert advanced.next_run_at == _NOW + timedelta(hours=1)
    assert advanced.last_fired_at is not None


def test_fire_records_a_dispatched_routine_run(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    task_id = fire_routine(ledger, trig, now=_NOW)
    runs = ledger.routine_runs.by_routine("r1")
    assert len(runs) == 1
    assert runs[0].status is RoutineRunStatus.DISPATCHED
    assert runs[0].linked_task_id == task_id


def test_second_fire_on_the_same_edge_is_a_noop(ledger: SqliteLedger) -> None:
    # Two ticks both see the edge due; only the first advances it and spawns work.
    trig = _routine(ledger)
    first = fire_routine(ledger, trig, now=_NOW)
    second = fire_routine(ledger, trig, now=_NOW)  # stale edge — claim_fire loses
    assert first is not None
    assert second is None
    assert len(ledger.routine_runs.by_routine("r1")) == 1


def test_skip_if_active_suppresses_while_prior_task_is_open(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    fire_routine(ledger, trig, now=_NOW)  # spawns task #1 (open)
    # Re-arm the edge so a second firing is eligible, prior task still open.
    ledger.routine_triggers.claim_fire(
        trig.id,
        expected_next_run_at=_NOW + timedelta(hours=1),
        new_next_run_at=_NOW + timedelta(hours=1),
    )
    re_armed = ledger.routine_triggers.get(trig.id)
    assert re_armed is not None
    later = _NOW + timedelta(hours=1)
    result = fire_routine(ledger, re_armed, now=later)
    assert result is None  # suppressed — prior routine task still open
    runs = ledger.routine_runs.by_routine("r1")
    assert any(r.status is RoutineRunStatus.SUPPRESSED for r in runs)


def test_coalesce_folds_onto_the_live_run(ledger: SqliteLedger) -> None:
    trig = _routine(ledger, concurrency=RoutineConcurrency.COALESCE)
    first = fire_routine(ledger, trig, now=_NOW)  # spawns task #1 (open) + a dispatched run
    assert first is not None
    survivor = next(
        r.id for r in ledger.routine_runs.by_routine("r1")
        if r.status is RoutineRunStatus.DISPATCHED
    )
    # re-arm the edge; fire again while the prior task is still open
    ledger.routine_triggers.claim_fire(
        trig.id,
        expected_next_run_at=_NOW + timedelta(hours=1),
        new_next_run_at=_NOW + timedelta(hours=1),
    )
    re_armed = ledger.routine_triggers.get(trig.id)
    assert re_armed is not None
    result = fire_routine(ledger, re_armed, now=_NOW + timedelta(hours=1))

    assert result is None  # no new task — folded onto the live run
    coalesced = [r for r in ledger.routine_runs.by_routine("r1") if r.status is RoutineRunStatus.COALESCED]
    assert len(coalesced) == 1
    assert coalesced[0].coalesced_into_run_id == survivor
    # only the one routine-spawned task exists
    assert ledger.tasks.has_open_for_routine("r1") is True


def test_always_spawns_even_while_prior_task_is_open(ledger: SqliteLedger) -> None:
    trig = _routine(ledger, concurrency=RoutineConcurrency.ALWAYS)
    first = fire_routine(ledger, trig, now=_NOW)  # task #1 (open)
    ledger.routine_triggers.claim_fire(
        trig.id,
        expected_next_run_at=_NOW + timedelta(hours=1),
        new_next_run_at=_NOW + timedelta(hours=1),
    )
    re_armed = ledger.routine_triggers.get(trig.id)
    assert re_armed is not None
    second = fire_routine(ledger, re_armed, now=_NOW + timedelta(hours=1))
    assert second is not None and second != first  # a fresh task, prior still open


def test_skip_missed_jumps_the_edge_past_now(ledger: SqliteLedger) -> None:
    # default catch-up: three hourly windows missed -> next edge is the first one after `now`
    trig = _routine(ledger)  # edge = _NOW (12:00)
    fire_routine(ledger, trig, now=_NOW + timedelta(hours=3, minutes=30))  # now = 15:30
    advanced = ledger.routine_triggers.get(trig.id)
    assert advanced is not None
    assert advanced.next_run_at == _NOW + timedelta(hours=4)  # 16:00, past now


def test_backfill_one_advances_a_single_step(ledger: SqliteLedger) -> None:
    # backfill: same three missed windows -> advance ONE step from the edge, catch up one per tick
    trig = _routine(ledger, catch_up=RoutineCatchUp.BACKFILL_ONE)  # edge = _NOW (12:00)
    fire_routine(ledger, trig, now=_NOW + timedelta(hours=3, minutes=30))  # now = 15:30
    advanced = ledger.routine_triggers.get(trig.id)
    assert advanced is not None
    assert advanced.next_run_at == _NOW + timedelta(hours=1)  # 13:00, still behind -> refires next tick


def test_skip_if_active_fires_once_prior_task_is_terminal(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    first = fire_routine(ledger, trig, now=_NOW)
    assert first is not None
    ledger.tasks.set_status(first, TaskStatus.DONE)  # prior task closed
    re_armed = ledger.routine_triggers.get(trig.id)
    assert re_armed is not None
    second = fire_routine(ledger, re_armed, now=_NOW + timedelta(hours=1))
    assert second is not None
    assert second != first


def test_next_beat_target_enqueues_a_note_wake_without_a_task(ledger: SqliteLedger) -> None:
    trig = _routine(ledger, target=RoutineTarget.NEXT_BEAT)
    result = fire_routine(ledger, trig, now=_NOW)
    assert result is None  # no task spawned
    queued = ledger.wakes.queued(employee_id="e1")
    assert len(queued) == 1
    assert queued[0].reason is WakeReason.CRON_DUE
    assert "note" in queued[0].payload
    assert "task_id" not in queued[0].payload


def test_fire_skips_a_paused_routine(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.routines.create(
        Routine(
            id="r_paused",
            employee_id="e1",
            intent_template="paused sweep",
            status=RoutineStatus.PAUSED,
        )
    )
    trig = ledger.routine_triggers.create(
        RoutineTrigger(
            id="trig_paused",
            routine_id="r_paused",
            cron_expression="0 * * * *",
            next_run_at=_NOW,
        )
    )
    assert fire_routine(ledger, trig, now=_NOW) is None
    assert ledger.routine_runs.by_routine("r_paused") == []


def test_fire_marks_wake_queued_for_normal_dispatch(ledger: SqliteLedger) -> None:
    trig = _routine(ledger)
    fire_routine(ledger, trig, now=_NOW)
    (wake,) = ledger.wakes.queued(employee_id="e1")
    assert wake.status is WakeStatus.QUEUED
