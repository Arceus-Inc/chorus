"""The valid-disposition contract (spec 02 §5).

When a beat *succeeds* but leaves the task ``in_progress`` with no human owner and no
live path — "finished" was recorded in the transcript but never in the task state —
chorus enqueues **one** corrective finish-handoff wake telling the employee to pick a
real disposition. If that wake is delivered and the task is *still* stranded, the ladder
is exhausted and chorus escalates: ``blocked`` + a ``missing_disposition`` recovery.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import (
    Run,
    RunStatus,
    WakeReason,
    WakeStatus,
)
from chorus.lifecycle import DispositionAction, reconcile_disposition
from chorus.workforce import Employee

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(seconds=60)


@pytest.fixture(autouse=True)
def emp(ledger: SqliteLedger) -> Employee:
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))


def _task(
    ledger: SqliteLedger,
    status: TaskStatus = TaskStatus.IN_PROGRESS,
    *,
    assignee_employee_id: str | None = "emp_1",
    assignee_user_id: str | None = None,
) -> Task:
    return ledger.tasks.submit(
        Task(
            id="t1",
            intent="ship it",
            status=status,
            assignee_employee_id=assignee_employee_id,
            assignee_user_id=assignee_user_id,
        )
    )


def _run(ledger: SqliteLedger, status: RunStatus, *, lease: datetime | None = None) -> Run:
    return ledger.runs.create(
        Run(
            id=f"run_{status.value}",
            employee_id="emp_1",
            task_id="t1",
            status=status,
            lease_expires_at=lease,
        )
    )


# -- the trigger: succeeded-but-undisposed enqueues exactly one wake -----------


def test_succeeded_run_left_in_progress_enqueues_one_finish_handoff(
    ledger: SqliteLedger, emp: Employee
) -> None:
    task = _task(ledger)
    _run(ledger, RunStatus.SUCCEEDED)
    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.HANDOFF_ENQUEUED
    queued = ledger.wakes.active_for_employee("emp_1")
    assert len(queued) == 1
    wake = queued[0]
    assert wake.reason is WakeReason.RECOVERY
    assert wake.payload.get("kind") == "finish_handoff"
    assert wake.payload.get("task_id") == "t1"


def test_finish_handoff_is_idempotent_while_pending(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger)
    _run(ledger, RunStatus.SUCCEEDED)
    reconcile_disposition(task, ledger, now=NOW)
    again = reconcile_disposition(task, ledger, now=NOW)
    # The pending wake IS a live path, so the second pass is a no-op, not a second nag.
    assert again.action is DispositionAction.NOOP
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


# -- guards: when NOT to nag ---------------------------------------------------


def test_human_owned_is_noop(ledger: SqliteLedger) -> None:
    task = _task(ledger, assignee_employee_id=None, assignee_user_id="u_1")
    _run(ledger, RunStatus.SUCCEEDED)
    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.NOOP
    assert result.reason == "human_owner"


def test_active_run_is_noop(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger)
    _run(ledger, RunStatus.RUNNING, lease=FUTURE)
    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.NOOP


def test_crashed_run_is_not_disposition(ledger: SqliteLedger, emp: Employee) -> None:
    # A failed run is continuity recovery (spec 02 §6), not a missing disposition.
    task = _task(ledger)
    _run(ledger, RunStatus.FAILED)
    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.NOOP
    assert result.reason == "no_successful_run"


def test_not_in_progress_is_noop(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.IN_REVIEW)
    _run(ledger, RunStatus.SUCCEEDED)
    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.NOOP
    assert result.reason == "not_in_progress"


# -- exhaustion: delivered handoff that didn't take -> escalate ---------------


def test_delivered_handoff_still_stranded_escalates_to_blocked_recovery(
    ledger: SqliteLedger, emp: Employee
) -> None:
    task = _task(ledger)
    _run(ledger, RunStatus.SUCCEEDED)
    reconcile_disposition(task, ledger, now=NOW)  # enqueues the handoff
    # Simulate the wake being delivered + consumed without the employee disposing.
    [wake] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(wake.id)
    assert wake.status is WakeStatus.CLAIMED  # (claimed by claim(); marked done above)

    result = reconcile_disposition(task, ledger, now=NOW)
    assert result.action is DispositionAction.ESCALATED
    blocked = ledger.tasks.get("t1")
    assert blocked is not None and blocked.status is TaskStatus.BLOCKED
    recovery = ledger.recovery_actions.active_for_source("t1")
    assert recovery is not None
    assert recovery.owner_employee_id == "emp_1"
