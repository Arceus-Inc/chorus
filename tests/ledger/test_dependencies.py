"""Task dependencies + dependency-gated eligibility (spec 01 Cluster A, spec 02/03).

``task_dependency`` is the real DAG edge ("A depends on B"). A task with an unresolved blocker is
withheld from ``list_eligible`` (no queued run until the blocker is ``done``); a ``cancelled``
blocker does **not** count as resolved (spec 02 §2). Self-edges and cycles are rejected.
"""

from __future__ import annotations

import pytest

from chorus.ledger import DependencyCycleError, Ledger, Task, TaskStatus
from chorus.testing import uid

pytestmark = pytest.mark.integration


def _task(ledger: Ledger, tid: str, status: TaskStatus = TaskStatus.TODO) -> None:
    ledger.tasks.submit(Task(id=tid, intent=tid, status=status))


def test_add_and_read_edges(ledger: Ledger) -> None:
    _task(ledger, uid("a"))
    _task(ledger, uid("b"))
    ledger.dependencies.add(uid("b"), uid("a"))  # b depends on a
    assert ledger.dependencies.blockers(uid("b")) == [uid("a")]
    assert ledger.dependencies.dependents(uid("a")) == [uid("b")]


def test_add_is_idempotent_and_returns_persisted_edge(ledger: Ledger) -> None:
    _task(ledger, uid("a"))
    _task(ledger, uid("b"))
    first = ledger.dependencies.add(uid("b"), uid("a"))
    second = ledger.dependencies.add(
        uid("b"), uid("a")
    )  # duplicate — must return the persisted edge
    assert ledger.dependencies.blockers(uid("b")) == [uid("a")]
    assert second.id == first.id  # not a freshly-generated, never-inserted id
    assert second.created_at == first.created_at


def test_remove_edge(ledger: Ledger) -> None:
    _task(ledger, uid("a"))
    _task(ledger, uid("b"))
    ledger.dependencies.add(uid("b"), uid("a"))
    ledger.dependencies.remove(uid("b"), uid("a"))
    assert ledger.dependencies.blockers(uid("b")) == []


def test_self_dependency_rejected(ledger: Ledger) -> None:
    _task(ledger, uid("a"))
    with pytest.raises(DependencyCycleError):
        ledger.dependencies.add(uid("a"), uid("a"))


def test_cycle_rejected(ledger: Ledger) -> None:
    for tid in (uid("a"), uid("b"), uid("c")):
        _task(ledger, tid)
    ledger.dependencies.add(uid("b"), uid("a"))  # b <- a
    ledger.dependencies.add(uid("c"), uid("b"))  # c <- b
    with pytest.raises(DependencyCycleError):
        ledger.dependencies.add(uid("a"), uid("c"))  # a <- c would close a -> c -> b -> a


def test_unresolved_blockers_excludes_done(ledger: Ledger) -> None:
    _task(ledger, uid("done_one"), TaskStatus.DONE)
    _task(ledger, uid("open_one"), TaskStatus.TODO)
    _task(ledger, uid("dep"))
    ledger.dependencies.add(uid("dep"), uid("done_one"))
    ledger.dependencies.add(uid("dep"), uid("open_one"))
    assert ledger.dependencies.unresolved_blockers(uid("dep")) == [uid("open_one")]


def test_newly_unblocked_dependents(ledger: Ledger) -> None:
    _task(ledger, uid("a"), TaskStatus.TODO)
    _task(ledger, uid("dep"), TaskStatus.TODO)
    ledger.dependencies.add(uid("dep"), uid("a"))
    assert ledger.dependencies.newly_unblocked_dependents(uid("a")) == []  # a still open
    ledger.tasks.set_status(uid("a"), TaskStatus.DONE)
    assert ledger.dependencies.newly_unblocked_dependents(uid("a")) == [uid("dep")]


def test_list_eligible_withholds_blocked_then_releases(ledger: Ledger) -> None:
    _task(ledger, uid("a"), TaskStatus.TODO)
    _task(ledger, uid("dep"), TaskStatus.TODO)
    ledger.dependencies.add(uid("dep"), uid("a"))
    before = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert uid("a") in before
    assert uid("dep") not in before  # blocked by a (todo)
    ledger.tasks.set_status(uid("a"), TaskStatus.DONE)
    after = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert uid("dep") in after  # blocker resolved


def test_cancelled_blocker_keeps_dependent_blocked(ledger: Ledger) -> None:
    _task(ledger, uid("a"), TaskStatus.TODO)
    _task(ledger, uid("dep"), TaskStatus.TODO)
    ledger.dependencies.add(uid("dep"), uid("a"))
    ledger.tasks.set_status(
        uid("a"), TaskStatus.CANCELLED
    )  # cancelled is NOT resolved (spec 02 §2)
    eligible = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert uid("dep") not in eligible
