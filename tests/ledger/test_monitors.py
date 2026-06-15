"""MonitorRepo — deferred self-wake (spec 01 Cluster B ``monitor``).

One-shot, for a task waiting on an external system (CI, deploy, review service). On fire it is
cleared and a ``monitor_due`` wake is queued; if the external thing still isn't done the assignee
must **re-arm** with a new ``next_check_at``. Re-arming an exhausted monitor is rejected. At most one
armed (pending) monitor per task. *Not* a recurring interval.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    Monitor,
    MonitorRecoveryPolicy,
    MonitorStatus,
    SqliteLedger,
    Task,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _setup(ledger: SqliteLedger, tid: str = "t1") -> str:
    ledger.tasks.submit(Task(id=tid, intent="x"))
    ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    return tid


def _at(seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def test_arm_and_get(ledger: SqliteLedger) -> None:
    _setup(ledger)
    armed = ledger.monitors.arm(
        Monitor(
            id="m1",
            task_id="t1",
            employee_id="e1",
            next_check_at=_at(60),
            notes="check CI",
            max_attempts=3,
            recovery_policy=MonitorRecoveryPolicy.CREATE_RECOVERY,
        )
    )
    got = ledger.monitors.get(armed.id)
    assert got is not None
    assert got.status is MonitorStatus.PENDING
    assert got.task_id == "t1"
    assert got.notes == "check CI"
    assert got.recovery_policy is MonitorRecoveryPolicy.CREATE_RECOVERY
    assert got.attempt_count == 0


def test_due_returns_ripe_pending_oldest_first(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.tasks.submit(Task(id="t2", intent="y"))
    ledger.monitors.arm(Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10)))
    ledger.monitors.arm(Monitor(id="m2", task_id="t2", employee_id="e1", next_check_at=_at(20)))
    ledger.tasks.submit(Task(id="t3", intent="z"))
    ledger.monitors.arm(Monitor(id="m3", task_id="t3", employee_id="e1", next_check_at=_at(999)))
    due = ledger.monitors.due(now=_at(100))
    assert [m.id for m in due] == ["m1", "m2"]


def test_at_most_one_armed_per_task(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10)))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.monitors.arm(Monitor(id="m2", task_id="t1", employee_id="e1", next_check_at=_at(20)))


def test_fire_is_one_shot_and_leaves_room_to_rearm(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10), max_attempts=3)
    )
    fired = ledger.monitors.fire("m1")
    assert fired.status is MonitorStatus.FIRED
    assert fired.attempt_count == 1
    assert fired.fired_at is not None


def test_fire_exhausts_when_attempts_run_out(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10), max_attempts=1)
    )
    fired = ledger.monitors.fire("m1")
    assert fired.status is MonitorStatus.EXHAUSTED


def test_rearm_returns_to_pending(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10), max_attempts=3)
    )
    ledger.monitors.fire("m1")
    rearmed = ledger.monitors.rearm("m1", next_check_at=_at(200))
    assert rearmed.status is MonitorStatus.PENDING
    assert rearmed.next_check_at == _at(200)


def test_rearm_exhausted_is_rejected(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10), max_attempts=1)
    )
    ledger.monitors.fire("m1")  # -> exhausted
    with pytest.raises(ValueError, match="exhausted"):
        ledger.monitors.rearm("m1", next_check_at=_at(200))


def test_fire_unknown_monitor_raises(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        ledger.monitors.fire("ghost")


def test_rearm_unknown_monitor_raises(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        ledger.monitors.rearm("ghost", next_check_at=_at(10))


def test_clear_frees_the_task(ledger: SqliteLedger) -> None:
    _setup(ledger)
    ledger.monitors.arm(Monitor(id="m1", task_id="t1", employee_id="e1", next_check_at=_at(10)))
    ledger.monitors.clear("m1")
    got = ledger.monitors.get("m1")
    assert got is not None
    assert got.status is MonitorStatus.CLEARED
    # task is free to arm a fresh monitor
    again = ledger.monitors.arm(
        Monitor(id="m2", task_id="t1", employee_id="e1", next_check_at=_at(300))
    )
    assert again.status is MonitorStatus.PENDING
