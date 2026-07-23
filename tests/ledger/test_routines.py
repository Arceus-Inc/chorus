"""Routine repos — cron (spec 01 Cluster C ``routine`` / ``routine_trigger`` / ``routine_run``).

A ``routine`` is a template + owner + policies; a ``routine_trigger`` is its schedule; a
``routine_run`` is one firing → one task. Firing is an optimistic-concurrency ``claim_fire`` on the
trigger's ``next_run_at`` so two ticks can't fire the same edge (the double-fire guard), and dispatch
is exact-once via the ``idempotency_key`` partial-unique index.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    Ledger,
    LedgerIntegrityError,
    Routine,
    RoutineRun,
    RoutineRunStatus,
    RoutineStatus,
    RoutineTrigger,
    Task,
    TriggerKind,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _at(seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def _employee(ledger: Ledger, eid: str = uid("e1")) -> str:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    return eid


def _routine(ledger: Ledger, rid: str = uid("r1")) -> str:
    _employee(ledger)
    ledger.routines.create(
        Routine(id=rid, employee_id=uid("e1"), intent_template="daily standup {date}")
    )
    return rid


# --- routine -------------------------------------------------------------------------------------


def test_routine_create_and_get(ledger: Ledger) -> None:
    _employee(ledger)
    created = ledger.routines.create(
        Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="review PRs {date}")
    )
    got = ledger.routines.get(created.id)
    assert got is not None
    assert got.employee_id == uid("e1")
    assert got.intent_template == "review PRs {date}"
    assert got.status is RoutineStatus.ACTIVE


def test_list_active_excludes_paused(ledger: Ledger) -> None:
    _employee(ledger)
    ledger.routines.create(Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="a"))
    ledger.routines.create(
        Routine(
            id=uid("r2"), employee_id=uid("e1"), intent_template="b", status=RoutineStatus.PAUSED
        )
    )
    assert [r.id for r in ledger.routines.list_active()] == [uid("r1")]


# --- routine_trigger -----------------------------------------------------------------------------


def test_trigger_create_and_due(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(
        RoutineTrigger(
            id=uid("tg1"),
            routine_id=uid("r1"),
            kind=TriggerKind.CRON,
            cron_expression="0 9 * * *",
            next_run_at=_at(10),
        )
    )
    ledger.routine_triggers.create(
        RoutineTrigger(id=uid("tg2"), routine_id=uid("r1"), next_run_at=_at(999))
    )
    due = ledger.routine_triggers.due(now=_at(100))
    assert [t.id for t in due] == [uid("tg1")]


def test_claim_fire_is_the_double_fire_guard(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(
        RoutineTrigger(id=uid("tg1"), routine_id=uid("r1"), next_run_at=_at(10))
    )
    # the tick that holds the current edge wins and advances next_run_at
    won = ledger.routine_triggers.claim_fire(
        uid("tg1"), expected_next_run_at=_at(10), new_next_run_at=_at(70)
    )
    assert won is True
    # a second tick still holding the stale edge loses — no double fire
    lost = ledger.routine_triggers.claim_fire(
        uid("tg1"), expected_next_run_at=_at(10), new_next_run_at=_at(70)
    )
    assert lost is False
    got = ledger.routine_triggers.get(uid("tg1"))
    assert got is not None
    assert got.next_run_at == _at(70)
    assert got.last_fired_at is not None


# --- routine_run ---------------------------------------------------------------------------------


def test_run_record_and_get(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(RoutineTrigger(id=uid("tg1"), routine_id=uid("r1")))
    rec = ledger.routine_runs.record(
        RoutineRun(
            id=uid("rr1"), routine_id=uid("r1"), trigger_id=uid("tg1"), idempotency_key="2026-01-01"
        )
    )
    got = ledger.routine_runs.get(rec.id)
    assert got is not None
    assert got.status is RoutineRunStatus.RECEIVED
    assert got.idempotency_key == "2026-01-01"


def test_idempotency_key_is_exact_once(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(RoutineTrigger(id=uid("tg1"), routine_id=uid("r1")))
    ledger.routine_runs.record(
        RoutineRun(id=uid("rr1"), routine_id=uid("r1"), trigger_id=uid("tg1"), idempotency_key="k1")
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.routine_runs.record(
            RoutineRun(
                id=uid("rr2"), routine_id=uid("r1"), trigger_id=uid("tg1"), idempotency_key="k1"
            )
        )


def test_null_idempotency_key_allows_many(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(RoutineTrigger(id=uid("tg1"), routine_id=uid("r1")))
    ledger.routine_runs.record(
        RoutineRun(id=uid("rr1"), routine_id=uid("r1"), trigger_id=uid("tg1"))
    )
    ledger.routine_runs.record(
        RoutineRun(id=uid("rr2"), routine_id=uid("r1"), trigger_id=uid("tg1"))
    )
    assert {r.id for r in ledger.routine_runs.by_routine(uid("r1"))} == {uid("rr1"), uid("rr2")}


def test_dispatch_links_task(ledger: Ledger) -> None:
    _routine(ledger)
    ledger.routine_triggers.create(RoutineTrigger(id=uid("tg1"), routine_id=uid("r1")))
    ledger.tasks.submit(Task(id=uid("t1"), intent="standup"))
    ledger.routine_runs.record(
        RoutineRun(id=uid("rr1"), routine_id=uid("r1"), trigger_id=uid("tg1"))
    )
    ledger.routine_runs.dispatch(uid("rr1"), linked_task_id=uid("t1"))
    got = ledger.routine_runs.get(uid("rr1"))
    assert got is not None
    assert got.status is RoutineRunStatus.DISPATCHED
    assert got.linked_task_id == uid("t1")
