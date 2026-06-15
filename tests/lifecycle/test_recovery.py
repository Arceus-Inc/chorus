"""The recovery ladder + tick reconcile sweep (spec 02 §6-§7, §9).

``reconcile`` is a pure function of the ledger — re-derived from rows, idempotent across
crash+restart. It runs the ordered sweep: (1) reap orphaned ``running`` runs whose lease
passed (release locks, crash recovery NOT retry); (3) reconcile stranded assigned work via
the bounded ladder (one wake, owner PRESERVED -> escalate to ``blocked`` + recovery); (4)
fold open recoveries whose source went terminal. It never auto-reassigns (spec 02 §8).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import (
    RecoveryAction,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryStatus,
    Run,
    RunStatus,
    WakeReason,
)
from chorus.recovery import reconcile
from chorus.workforce import Employee

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(seconds=60)
PAST = NOW - timedelta(seconds=60)


@pytest.fixture(autouse=True)
def emp(ledger: SqliteLedger) -> Employee:
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))


def _task(
    ledger: SqliteLedger,
    status: TaskStatus,
    *,
    task_id: str = "t1",
    assignee_employee_id: str | None = "emp_1",
    assignee_user_id: str | None = None,
    checkout_run_id: str | None = None,
    execution_run_id: str | None = None,
) -> Task:
    return ledger.tasks.submit(
        Task(
            id=task_id,
            intent="ship it",
            status=status,
            assignee_employee_id=assignee_employee_id,
            assignee_user_id=assignee_user_id,
            checkout_run_id=checkout_run_id,
            execution_run_id=execution_run_id,
        )
    )


def _run(
    ledger: SqliteLedger,
    status: RunStatus,
    *,
    run_id: str | None = None,
    task_id: str = "t1",
    lease: datetime | None = None,
) -> Run:
    return ledger.runs.create(
        Run(
            id=run_id or f"run_{status.value}",
            employee_id="emp_1",
            task_id=task_id,
            status=status,
            lease_expires_at=lease,
        )
    )


# -- §7 step 1: reap orphaned running runs (lease passed) ----------------------


def test_reap_orphaned_running_run_releases_locks(ledger: SqliteLedger) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id="run_dead",
        execution_run_id="run_dead",
    )
    _run(ledger, RunStatus.RUNNING, run_id="run_dead", lease=PAST)

    report = reconcile(ledger, now=NOW)

    assert "run_dead" in report.reaped_runs
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.checkout_run_id is None  # crash recovery: the lock is released
    assert task.execution_run_id is None
    reaped = ledger.runs.get("run_dead")
    assert reaped is not None
    assert reaped.status is RunStatus.TIMED_OUT


def test_running_run_with_future_lease_is_not_reaped(ledger: SqliteLedger) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id="run_live",
        execution_run_id="run_live",
    )
    _run(ledger, RunStatus.RUNNING, run_id="run_live", lease=FUTURE)

    report = reconcile(ledger, now=NOW)

    assert report.reaped_runs == []
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.checkout_run_id == "run_live"  # live owner, untouched
    assert "t1" not in report.recovered  # an active run is a live path


# -- §9 mode a: stranded todo -> one assignment-recovery wake ------------------


def test_stranded_todo_enqueues_one_assignment_recovery_wake(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    report = reconcile(ledger, now=NOW)

    assert "t1" in report.recovered
    wakes = ledger.wakes.active_for_employee("emp_1")
    assert len(wakes) == 1
    wake = wakes[0]
    assert wake.reason is WakeReason.RECOVERY
    assert wake.payload["kind"] == "assignment_recovery"
    assert wake.payload["task_id"] == "t1"
    # The owner is preserved — never auto-reassigned (spec 02 §8).
    assert wake.employee_id == "emp_1"
    # Tier 1 only: the task stays todo, no recovery card yet.
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.TODO
    assert ledger.recovery_actions.active_for_source("t1") is None


def test_recovery_never_reassigns_to_a_different_employee(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="emp_2", name="bob", role="engineer"))
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)

    assert ledger.wakes.active_for_employee("emp_2") == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_recovery_wake_is_idempotent_while_pending(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)
    second = reconcile(ledger, now=NOW)

    # The pending wake is itself a live path, so the second pass is a no-op.
    assert second.recovered == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_recovery_wake_carries_the_cheap_lane_guards(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)

    wake = ledger.wakes.active_for_employee("emp_1")[0]
    assert wake.payload["lane"] == "cheap"
    assert wake.payload["allow_deliverable_work"] is False
    assert wake.payload["allow_document_updates"] is False
    assert wake.payload["resume_requires_normal"] is True


# -- §9 mode b: stranded in_progress -> one continuation wake ------------------


def test_stranded_in_progress_enqueues_one_continuation_wake(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.IN_PROGRESS)
    _run(ledger, RunStatus.FAILED)  # the live run disappeared

    report = reconcile(ledger, now=NOW)

    assert "t1" in report.recovered
    wakes = ledger.wakes.active_for_employee("emp_1")
    assert len(wakes) == 1
    assert wakes[0].payload["kind"] == "continuation"
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS  # tier 1: still in_progress


# -- ladder exhaustion: delivered wake + still stranded -> blocked + recovery --


def _deliver_recovery_wake(ledger: SqliteLedger) -> None:
    [wake] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(wake.id)


def test_delivered_recovery_wake_still_stranded_escalates_to_blocked(
    ledger: SqliteLedger,
) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)  # tier 1: enqueue one wake
    _deliver_recovery_wake(ledger)  # the employee ran it and it's still stranded
    report = reconcile(ledger, now=NOW)  # tier 2: escalate

    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    action = ledger.recovery_actions.active_for_source("t1")
    assert action is not None
    assert action.id in report.opened
    assert action.kind is RecoveryKind.STRANDED
    assert action.owner_employee_id == "emp_1"  # owner preserved
    assert action.status is RecoveryStatus.ACTIVE


def test_open_recovery_is_a_live_path_and_is_not_reopened(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)
    reconcile(ledger, now=NOW)
    _deliver_recovery_wake(ledger)
    reconcile(ledger, now=NOW)  # escalates -> blocked + recovery
    first = ledger.recovery_actions.active_for_source("t1")

    third = reconcile(ledger, now=NOW)  # the open recovery IS a live path

    assert third.opened == []
    again = ledger.recovery_actions.active_for_source("t1")
    assert first is not None and again is not None
    assert again.id == first.id  # exact-once: no duplicate card


# -- in_review stall: no dispatch to retry -> open a recovery card directly ----


def test_stranded_in_review_opens_a_recovery_directly(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.IN_REVIEW)

    report = reconcile(ledger, now=NOW)

    action = ledger.recovery_actions.active_for_source("t1")
    assert action is not None
    assert action.id in report.opened
    assert action.owner_employee_id == "emp_1"
    assert report.recovered == []  # no retry wake — there's no dispatch to resume
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.IN_REVIEW  # the open card is the live path


# -- §6 source-aware folding: source went terminal -> fold the alert -----------


def test_open_recovery_is_folded_when_source_becomes_terminal(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.DONE)
    ledger.recovery_actions.open(
        RecoveryAction(
            id="rec_stale",
            source_task_id="t1",
            kind=RecoveryKind.STRANDED,
            owner_employee_id="emp_1",
            cause="stranded_todo",
            fingerprint="recovery",
        )
    )

    report = reconcile(ledger, now=NOW)

    assert "rec_stale" in report.folded
    action = ledger.recovery_actions.get("rec_stale")
    assert action is not None
    assert action.status is RecoveryStatus.RESOLVED
    assert action.outcome is RecoveryOutcome.FALSE_POSITIVE
    assert ledger.recovery_actions.active_for_source("t1") is None


# -- idempotency & non-interference -------------------------------------------


def test_reconcile_is_idempotent(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    first = reconcile(ledger, now=NOW)
    second = reconcile(ledger, now=NOW)

    assert "t1" in first.recovered
    assert second.recovered == []
    assert second.opened == []
    assert second.folded == []
    assert second.reaped_runs == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_healthy_tasks_are_left_untouched(ledger: SqliteLedger) -> None:
    _task(ledger, TaskStatus.TODO, task_id="resting")  # no interrupted run -> healthy
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        task_id="human",
        assignee_employee_id=None,
        assignee_user_id="u_1",
    )
    _task(ledger, TaskStatus.DONE, task_id="done")

    report = reconcile(ledger, now=NOW)

    assert report.recovered == []
    assert report.opened == []
    assert ledger.wakes.active_for_employee("emp_1") == []
