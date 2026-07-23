"""The dispatch substrate — deterministic wake claim + the running-run count (spec 03 §3d, §5).

Push-only dispatch claims wakes in the kernel's priority order, not arrival order: an
**in_progress** task (resume) outranks a fresh **todo**, a **deps-ready** task outranks a gated one,
then the priority band, then FIFO (``created_at``), then the wake id as a stable tiebreak. ``claim``
encodes that order so the scheduler dispatches the most-deserving work first; ``count_running`` feeds
``free_slots`` — the concurrency budget gate.
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Wake, WakeReason
from chorus.ledger import Ledger, Run, Task
from chorus.ledger._models import RunStatus, TaskPriority, TaskStatus
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str = uid("e1")) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def _task(
    ledger: Ledger,
    tid: str,
    *,
    status: TaskStatus = TaskStatus.TODO,
    priority: TaskPriority = TaskPriority.MEDIUM,
) -> None:
    ledger.tasks.submit(Task(id=tid, intent=tid, priority=priority))
    if status is not TaskStatus.BACKLOG:
        ledger.tasks.set_status(tid, status)


def _wake(ledger: Ledger, *, wid: str, task: str, eid: str = uid("e1")) -> Wake:
    return ledger.wakes.enqueue(
        Wake(id=wid, employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": task})
    )


# --- count_running -----------------------------------------------------------------------------


def test_count_running_counts_only_running_runs(ledger: Ledger) -> None:
    _emp(ledger)
    _task(ledger, uid("t1"))
    _task(ledger, uid("t2"))
    _task(ledger, uid("t3"))
    ledger.runs.create(
        Run(id=uid("r1"), employee_id=uid("e1"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.runs.create(
        Run(id=uid("r2"), employee_id=uid("e1"), task_id=uid("t2"), status=RunStatus.RUNNING)
    )
    ledger.runs.create(
        Run(id=uid("r3"), employee_id=uid("e1"), task_id=uid("t3"), status=RunStatus.SUCCEEDED)
    )
    assert ledger.runs.count_running() == 2


def test_count_running_zero_when_idle(ledger: Ledger) -> None:
    assert ledger.runs.count_running() == 0


# --- deterministic claim order ----------------------------------------------------------------


def test_claim_resume_before_new(ledger: Ledger) -> None:
    """An in_progress task (a resume) outranks a fresh todo of equal priority."""
    _emp(ledger)
    _task(ledger, uid("todo_task"), status=TaskStatus.TODO)
    _task(ledger, uid("live_task"), status=TaskStatus.IN_PROGRESS)
    _wake(ledger, wid=uid("w_todo"), task=uid("todo_task"))
    _wake(ledger, wid=uid("w_live"), task=uid("live_task"))
    claimed = ledger.wakes.claim(limit=2)
    assert [w.id for w in claimed] == [uid("w_live"), uid("w_todo")]


def test_claim_deps_ready_before_gated(ledger: Ledger) -> None:
    """A task whose blockers are all done outranks one still waiting on a blocker."""
    _emp(ledger)
    _task(ledger, uid("blocker"), status=TaskStatus.TODO)
    _task(ledger, uid("gated"), status=TaskStatus.TODO)
    ledger.dependencies.add(uid("gated"), uid("blocker"))  # gated waits on an unfinished blocker
    _task(ledger, uid("ready"), status=TaskStatus.TODO)
    _wake(ledger, wid=uid("w_gated"), task=uid("gated"))
    _wake(ledger, wid=uid("w_ready"), task=uid("ready"))
    claimed = ledger.wakes.claim(limit=2)
    assert [w.id for w in claimed] == [uid("w_ready"), uid("w_gated")]


def test_claim_resolved_blocker_is_deps_ready(ledger: Ledger) -> None:
    """A done blocker no longer gates — the dependent sorts as deps-ready."""
    _emp(ledger)
    _task(ledger, uid("blocker"), status=TaskStatus.DONE)
    _task(ledger, uid("dependent"), status=TaskStatus.TODO)
    ledger.dependencies.add(uid("dependent"), uid("blocker"))
    _task(ledger, uid("plain"), status=TaskStatus.TODO)
    w_dep = _wake(ledger, wid=uid("w_dep"), task=uid("dependent"))
    w_plain = _wake(ledger, wid=uid("w_plain"), task=uid("plain"))
    claimed = ledger.wakes.claim(limit=2)
    # Both deps-ready, same band → FIFO by enqueue order.
    assert {w.id for w in claimed} == {w_dep.id, w_plain.id}
    assert [w.id for w in claimed] == [uid("w_dep"), uid("w_plain")]


def test_claim_orders_by_priority_band(ledger: Ledger) -> None:
    """critical < high < medium < low, regardless of arrival order."""
    _emp(ledger)
    _task(ledger, uid("t_low"), priority=TaskPriority.LOW)
    _task(ledger, uid("t_crit"), priority=TaskPriority.CRITICAL)
    _task(ledger, uid("t_med"), priority=TaskPriority.MEDIUM)
    _task(ledger, uid("t_high"), priority=TaskPriority.HIGH)
    _wake(ledger, wid=uid("w_low"), task=uid("t_low"))
    _wake(ledger, wid=uid("w_crit"), task=uid("t_crit"))
    _wake(ledger, wid=uid("w_med"), task=uid("t_med"))
    _wake(ledger, wid=uid("w_high"), task=uid("t_high"))
    claimed = ledger.wakes.claim(limit=4)
    assert [w.id for w in claimed] == [uid("w_crit"), uid("w_high"), uid("w_med"), uid("w_low")]


def test_claim_fifo_within_band(ledger: Ledger) -> None:
    """Same status + priority → oldest wake first."""
    _emp(ledger)
    for i in (1, 2, 3):
        _task(ledger, uid(f"t{i}"))
        _wake(ledger, wid=uid(f"w{i}"), task=uid(f"t{i}"))
    claimed = ledger.wakes.claim(limit=3)
    assert [w.id for w in claimed] == [uid("w1"), uid("w2"), uid("w3")]


def test_claim_breaks_created_at_tie_by_wake_id(ledger: Ledger) -> None:
    """When everything else ties, the wake id is the stable tiebreak."""
    _emp(ledger)
    _task(ledger, uid("ta"))
    _task(ledger, uid("tb"))
    _wake(ledger, wid=uid("w_b"), task=uid("tb"))
    _wake(ledger, wid=uid("w_a"), task=uid("ta"))
    # Force an exact created_at tie so only the id can order the two.
    ledger._conn.execute("UPDATE wake SET created_at = '2026-01-01T00:00:00+00:00'")
    ledger._conn.commit()
    claimed = ledger.wakes.claim(limit=2)
    assert [w.id for w in claimed] == [uid("w_a"), uid("w_b")]


def test_claim_respects_limit_taking_the_top(ledger: Ledger) -> None:
    """limit caps the claim and takes the highest-ranked wakes, leaving the rest queued."""
    _emp(ledger)
    _task(ledger, uid("t_low"), priority=TaskPriority.LOW)
    _task(ledger, uid("t_crit"), priority=TaskPriority.CRITICAL)
    _task(ledger, uid("t_high"), priority=TaskPriority.HIGH)
    _wake(ledger, wid=uid("w_low"), task=uid("t_low"))
    _wake(ledger, wid=uid("w_crit"), task=uid("t_crit"))
    _wake(ledger, wid=uid("w_high"), task=uid("t_high"))
    claimed = ledger.wakes.claim(limit=2)
    assert [w.id for w in claimed] == [uid("w_crit"), uid("w_high")]
    assert [w.id for w in ledger.wakes.queued()] == [uid("w_low")]


def test_claim_handles_wake_without_task(ledger: Ledger) -> None:
    """A task-less wake (e.g. a message) still claims, sorting as low/deps-ready."""
    _emp(ledger)
    _task(ledger, uid("t_crit"), priority=TaskPriority.CRITICAL)
    ledger.wakes.enqueue(
        Wake(id=uid("w_msg"), employee_id=uid("e1"), reason=WakeReason.MESSAGE, payload={})
    )
    _wake(ledger, wid=uid("w_task"), task=uid("t_crit"))
    claimed = ledger.wakes.claim(limit=2)
    # The critical task outranks the task-less message.
    assert [w.id for w in claimed] == [uid("w_task"), uid("w_msg")]
