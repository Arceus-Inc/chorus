"""Task dependencies + dependency-gated eligibility (spec 01 Cluster A, spec 02/03).

``task_dependency`` is the real DAG edge ("A depends on B"). A task with an unresolved blocker is
withheld from ``list_eligible`` (no queued run until the blocker is ``done``); a ``cancelled``
blocker does **not** count as resolved (spec 02 §2). Self-edges and cycles are rejected.
"""

from __future__ import annotations

import pytest

from chorus.ledger import DependencyCycleError, SqliteLedger, Task, TaskStatus

pytestmark = pytest.mark.integration


def _task(ledger: SqliteLedger, tid: str, status: TaskStatus = TaskStatus.TODO) -> None:
    ledger.tasks.submit(Task(id=tid, intent=tid, status=status))


def test_add_and_read_edges(ledger: SqliteLedger) -> None:
    _task(ledger, "a")
    _task(ledger, "b")
    ledger.dependencies.add("b", "a")  # b depends on a
    assert ledger.dependencies.blockers("b") == ["a"]
    assert ledger.dependencies.dependents("a") == ["b"]


def test_add_is_idempotent(ledger: SqliteLedger) -> None:
    _task(ledger, "a")
    _task(ledger, "b")
    ledger.dependencies.add("b", "a")
    ledger.dependencies.add("b", "a")  # same edge again — no-op
    assert ledger.dependencies.blockers("b") == ["a"]


def test_remove_edge(ledger: SqliteLedger) -> None:
    _task(ledger, "a")
    _task(ledger, "b")
    ledger.dependencies.add("b", "a")
    ledger.dependencies.remove("b", "a")
    assert ledger.dependencies.blockers("b") == []


def test_self_dependency_rejected(ledger: SqliteLedger) -> None:
    _task(ledger, "a")
    with pytest.raises(DependencyCycleError):
        ledger.dependencies.add("a", "a")


def test_cycle_rejected(ledger: SqliteLedger) -> None:
    for tid in ("a", "b", "c"):
        _task(ledger, tid)
    ledger.dependencies.add("b", "a")  # b <- a
    ledger.dependencies.add("c", "b")  # c <- b
    with pytest.raises(DependencyCycleError):
        ledger.dependencies.add("a", "c")  # a <- c would close a -> c -> b -> a


def test_unresolved_blockers_excludes_done(ledger: SqliteLedger) -> None:
    _task(ledger, "done_one", TaskStatus.DONE)
    _task(ledger, "open_one", TaskStatus.TODO)
    _task(ledger, "dep")
    ledger.dependencies.add("dep", "done_one")
    ledger.dependencies.add("dep", "open_one")
    assert ledger.dependencies.unresolved_blockers("dep") == ["open_one"]


def test_newly_unblocked_dependents(ledger: SqliteLedger) -> None:
    _task(ledger, "a", TaskStatus.TODO)
    _task(ledger, "dep", TaskStatus.TODO)
    ledger.dependencies.add("dep", "a")
    assert ledger.dependencies.newly_unblocked_dependents("a") == []  # a still open
    ledger.tasks.set_status("a", TaskStatus.DONE)
    assert ledger.dependencies.newly_unblocked_dependents("a") == ["dep"]


def test_list_eligible_withholds_blocked_then_releases(ledger: SqliteLedger) -> None:
    _task(ledger, "a", TaskStatus.TODO)
    _task(ledger, "dep", TaskStatus.TODO)
    ledger.dependencies.add("dep", "a")
    before = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert "a" in before
    assert "dep" not in before  # blocked by a (todo)
    ledger.tasks.set_status("a", TaskStatus.DONE)
    after = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert "dep" in after  # blocker resolved


def test_cancelled_blocker_keeps_dependent_blocked(ledger: SqliteLedger) -> None:
    _task(ledger, "a", TaskStatus.TODO)
    _task(ledger, "dep", TaskStatus.TODO)
    ledger.dependencies.add("dep", "a")
    ledger.tasks.set_status("a", TaskStatus.CANCELLED)  # cancelled is NOT resolved (spec 02 §2)
    eligible = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert "dep" not in eligible
