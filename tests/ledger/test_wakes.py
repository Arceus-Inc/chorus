"""WakeRepo — the coalescing push inbox (spec 01 Cluster C ``wake``, spec 03 §2).

A wake is "run employee E because reason R". Coalescing is a DB guarantee (the partial-unique
``wake_queued_key_uq`` index): a flurry of identical triggers folds into one *queued* wake
(``coalesced_count`` bumped), so the employee runs once — but coalescing applies only while a wake
is ``queued`` (a new trigger after one is claimed enqueues fresh work).
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Wake, WakeReason, WakeStatus
from chorus.ledger import Ledger, Run, Task
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str = uid("e1")) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def _wake(*, wid: str, task: str = uid("t1"), eid: str = uid("e1")) -> Wake:
    return Wake(id=wid, employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": task})


def test_enqueue_and_get(ledger: Ledger) -> None:
    _emp(ledger)
    enqueued = ledger.wakes.enqueue(_wake(wid=uid("w1")))
    got = ledger.wakes.get(enqueued.id)
    assert got is not None
    assert got.employee_id == uid("e1")
    assert got.reason is WakeReason.TASK_ASSIGNED
    assert got.status is WakeStatus.QUEUED
    assert got.payload["task_id"] == uid("t1")
    assert got.coalesced_count == 0


def test_enqueue_coalesces_queued(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(_wake(wid=uid("w1")))
    second = ledger.wakes.enqueue(_wake(wid=uid("w2")))  # same default key e1:task_assigned:t1
    queued = ledger.wakes.queued()
    assert len(queued) == 1
    assert queued[0].coalesced_count == 1
    assert second.id == queued[0].id  # returns the persisted (existing) row, not the new id


def test_distinct_keys_do_not_coalesce(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(_wake(wid=uid("w1"), task=uid("t1")))
    ledger.wakes.enqueue(_wake(wid=uid("w2"), task=uid("t2")))
    assert len(ledger.wakes.queued()) == 2


def test_claim_takes_oldest_and_marks_claimed(ledger: Ledger) -> None:
    _emp(ledger)
    for i in (1, 2, 3):
        ledger.wakes.enqueue(_wake(wid=uid(f"w{i}"), task=uid(f"t{i}")))
    claimed = ledger.wakes.claim(limit=2)
    assert [w.id for w in claimed] == [uid("w1"), uid("w2")]
    assert all(w.status is WakeStatus.CLAIMED for w in claimed)
    assert [w.id for w in ledger.wakes.queued()] == [uid("w3")]


def test_claimed_wake_is_not_reclaimed(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(_wake(wid=uid("w1")))
    ledger.wakes.claim(limit=10)
    assert ledger.wakes.claim(limit=10) == []


def test_coalesce_applies_only_to_queued(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(_wake(wid=uid("w1"), task=uid("t1")))
    ledger.wakes.claim(limit=10)  # w1 now claimed
    fresh = ledger.wakes.enqueue(
        _wake(wid=uid("w2"), task=uid("t1"))
    )  # same key, prior is claimed → new row
    assert fresh.id == uid("w2")
    assert fresh.status is WakeStatus.QUEUED
    assert len(ledger.wakes.queued()) == 1


def test_mark_done(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.wakes.enqueue(_wake(wid=uid("w1")))
    ledger.wakes.claim(limit=10)
    ledger.wakes.mark_done(uid("w1"))
    got = ledger.wakes.get(uid("w1"))
    assert got is not None
    assert got.status is WakeStatus.DONE


def test_assign_run(ledger: Ledger) -> None:
    _emp(ledger)
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(Run(id=uid("r1"), employee_id=uid("e1"), task_id=uid("t1")))
    ledger.wakes.enqueue(_wake(wid=uid("w1"), task=uid("t1")))
    ledger.wakes.claim(limit=10)
    ledger.wakes.assign_run(uid("w1"), uid("r1"))
    got = ledger.wakes.get(uid("w1"))
    assert got is not None
    assert got.run_id == uid("r1")
