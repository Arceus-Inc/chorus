"""MonitorRepo — deferred self-wake (spec 01 Cluster B ``monitor``).

One-shot, for a task waiting on an external system (CI, deploy, review service). On fire it is
cleared and a ``monitor_due`` wake is queued; if the external thing still isn't done the assignee
must **re-arm** with a new ``next_check_at``. Re-arming an exhausted monitor is rejected. At most one
armed (pending) monitor per task. *Not* a recurring interval.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    Ledger,
    LedgerIntegrityError,
    Monitor,
    MonitorRecoveryPolicy,
    MonitorStatus,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _setup(ledger: Ledger, tid: str = uid("t1")) -> str:
    ledger.tasks.submit(Task(id=tid, intent="x"))
    ledger.employees.create(Employee(id=uid("e1"), name=uid("e1"), role="engineer"))
    return tid


def _at(seconds: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=seconds)


def test_arm_and_get(ledger: Ledger) -> None:
    _setup(ledger)
    armed = ledger.monitors.arm(
        Monitor(
            id=uid("m1"),
            task_id=uid("t1"),
            employee_id=uid("e1"),
            next_check_at=_at(60),
            notes="check CI",
            max_attempts=3,
            recovery_policy=MonitorRecoveryPolicy.CREATE_RECOVERY,
        )
    )
    got = ledger.monitors.get(armed.id)
    assert got is not None
    assert got.status is MonitorStatus.PENDING
    assert got.task_id == uid("t1")
    assert got.notes == "check CI"
    assert got.recovery_policy is MonitorRecoveryPolicy.CREATE_RECOVERY
    assert got.attempt_count == 0


def test_due_returns_ripe_pending_oldest_first(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.tasks.submit(Task(id=uid("t2"), intent="y"))
    ledger.monitors.arm(
        Monitor(id=uid("m1"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_at(10))
    )
    ledger.monitors.arm(
        Monitor(id=uid("m2"), task_id=uid("t2"), employee_id=uid("e1"), next_check_at=_at(20))
    )
    ledger.tasks.submit(Task(id=uid("t3"), intent="z"))
    ledger.monitors.arm(
        Monitor(id=uid("m3"), task_id=uid("t3"), employee_id=uid("e1"), next_check_at=_at(999))
    )
    due = ledger.monitors.due(now=_at(100))
    assert [m.id for m in due] == [uid("m1"), uid("m2")]


def test_at_most_one_armed_per_task(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id=uid("m1"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_at(10))
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.monitors.arm(
            Monitor(id=uid("m2"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_at(20))
        )


def test_fire_is_one_shot_and_leaves_room_to_rearm(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(
            id=uid("m1"),
            task_id=uid("t1"),
            employee_id=uid("e1"),
            next_check_at=_at(10),
            max_attempts=3,
        )
    )
    fired = ledger.monitors.fire(uid("m1"))
    assert fired.status is MonitorStatus.FIRED
    assert fired.attempt_count == 1
    assert fired.fired_at is not None


def test_fire_exhausts_when_attempts_run_out(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(
            id=uid("m1"),
            task_id=uid("t1"),
            employee_id=uid("e1"),
            next_check_at=_at(10),
            max_attempts=1,
        )
    )
    fired = ledger.monitors.fire(uid("m1"))
    assert fired.status is MonitorStatus.EXHAUSTED


def test_rearm_returns_to_pending(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(
            id=uid("m1"),
            task_id=uid("t1"),
            employee_id=uid("e1"),
            next_check_at=_at(10),
            max_attempts=3,
        )
    )
    ledger.monitors.fire(uid("m1"))
    rearmed = ledger.monitors.rearm(uid("m1"), next_check_at=_at(200))
    assert rearmed.status is MonitorStatus.PENDING
    assert rearmed.next_check_at == _at(200)


def test_rearm_exhausted_is_rejected(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(
            id=uid("m1"),
            task_id=uid("t1"),
            employee_id=uid("e1"),
            next_check_at=_at(10),
            max_attempts=1,
        )
    )
    ledger.monitors.fire(uid("m1"))  # -> exhausted
    with pytest.raises(ValueError, match="exhausted"):
        ledger.monitors.rearm(uid("m1"), next_check_at=_at(200))


def test_fire_unknown_monitor_raises(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        ledger.monitors.fire(uid("ghost"))


def test_rearm_unknown_monitor_raises(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        ledger.monitors.rearm(uid("ghost"), next_check_at=_at(10))


def test_clear_frees_the_task(ledger: Ledger) -> None:
    _setup(ledger)
    ledger.monitors.arm(
        Monitor(id=uid("m1"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_at(10))
    )
    ledger.monitors.clear(uid("m1"))
    got = ledger.monitors.get(uid("m1"))
    assert got is not None
    assert got.status is MonitorStatus.CLEARED
    # task is free to arm a fresh monitor
    again = ledger.monitors.arm(
        Monitor(id=uid("m2"), task_id=uid("t1"), employee_id=uid("e1"), next_check_at=_at(300))
    )
    assert again.status is MonitorStatus.PENDING
