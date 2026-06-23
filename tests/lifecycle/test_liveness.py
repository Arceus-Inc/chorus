"""The liveness contract (spec 02 §3).

An agent-owned, non-terminal task is **healthy** iff it has at least one
action-path primitive — otherwise it is **stalled** and must be surfaced as
recovery work. These tests pin one primitive per case (so each is the *sole*
reason the task is healthy) plus the per-status nuances (todo resting-vs-stranded,
in_progress quiet-run-not-stalled, in_review review-path, blocked first-stalled-leaf).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import (
    Approval,
    ApprovalSubjectKind,
    Monitor,
    Run,
    RunStatus,
    Wake,
    WakeReason,
)
from chorus.lifecycle import Health, Liveness, classify
from chorus.workforce import Employee

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(seconds=60)
PAST = NOW - timedelta(seconds=60)


@pytest.fixture
def emp(ledger: SqliteLedger) -> Employee:
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))


def _task(
    ledger: SqliteLedger,
    status: TaskStatus,
    *,
    task_id: str = "t1",
    assignee_employee_id: str | None = "emp_1",
    assignee_user_id: str | None = None,
) -> Task:
    return ledger.tasks.submit(
        Task(
            id=task_id,
            intent="ship it",
            status=status,
            assignee_employee_id=assignee_employee_id,
            assignee_user_id=assignee_user_id,
        )
    )


def _running_run(ledger: SqliteLedger, task_id: str, *, lease: datetime) -> Run:
    return ledger.runs.create(
        Run(
            id=f"run_{task_id}",
            employee_id="emp_1",
            task_id=task_id,
            status=RunStatus.RUNNING,
            lease_expires_at=lease,
        )
    )


# -- universal short circuits -------------------------------------------------


@pytest.mark.parametrize("status", [TaskStatus.DONE, TaskStatus.CANCELLED])
def test_terminal_is_healthy(ledger: SqliteLedger, emp: Employee, status: TaskStatus) -> None:
    task = _task(ledger, status)
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "terminal"


def test_human_owned_is_healthy(ledger: SqliteLedger) -> None:
    task = _task(ledger, TaskStatus.TODO, assignee_employee_id=None, assignee_user_id="u_1")
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "human_owner"


def test_backlog_is_parked_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.BACKLOG)
    assert classify(task, ledger, now=NOW) == Liveness(Health.HEALTHY, "backlog_parked")


# -- todo: resting vs stranded ------------------------------------------------


def test_todo_with_queued_wake_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.TODO)
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="emp_1", reason=WakeReason.TASK_ASSIGNED, payload={"task_id": "t1"})
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "queued_wake"


def test_todo_with_no_run_and_no_wake_is_stranded(ledger: SqliteLedger, emp: Employee) -> None:
    # No runs, no wake, no recovery: nothing will ever pick it up. `assign_task` enqueues a
    # `task_assigned` wake atomically with backlog→todo, so a wake-less, run-less todo is *abandoned*,
    # not "resting" — "resting" is only valid after a clean success (spec 02 §9, paperclip
    # hasExplicitWaitingPath). This is the tinyvec stranded-todo: a never-dispatched leaf hangs its parent.
    task = _task(ledger, TaskStatus.TODO)
    result = classify(task, ledger, now=NOW)
    assert result.stalled
    assert result.reason == "stranded_todo"


def test_todo_after_succeeded_run_is_resting_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.TODO)
    ledger.runs.create(
        Run(id="run_ok", employee_id="emp_1", task_id="t1", status=RunStatus.SUCCEEDED)
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "resting"


def test_todo_awaiting_an_unresolved_dependency_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    # A todo whose assignment wake was gated by an unresolved dependency is WAITING, not stranded: the
    # scheduler marks the assignment wake done, and a ``deps_resolved`` wake re-dispatches it once the
    # blocker lands. Without this, every dependency-gated child reads "stranded" in the gap before
    # deps_resolved fires — spurious recovery churn (the V3 over-fire: 100% of stranded recoveries were
    # dep-gated todos with no wake/run yet, all opened <30s after creation and immediately folded).
    task = _task(ledger, TaskStatus.TODO, task_id="t1")  # no wake, no run yet
    _task(ledger, TaskStatus.IN_PROGRESS, task_id="t2")  # its blocker, still being worked
    ledger.dependencies.add("t1", "t2")
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "awaiting_dependency"


@pytest.mark.parametrize("bad", [RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED])
def test_todo_with_interrupted_dispatch_is_stalled(
    ledger: SqliteLedger, emp: Employee, bad: RunStatus
) -> None:
    task = _task(ledger, TaskStatus.TODO)
    ledger.runs.create(Run(id="run_bad", employee_id="emp_1", task_id="t1", status=bad))
    result = classify(task, ledger, now=NOW)
    assert result.stalled
    assert result.reason == "stranded_todo"


def test_stranded_todo_with_open_recovery_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    from chorus.ledger._models import RecoveryAction, RecoveryKind

    task = _task(ledger, TaskStatus.TODO)
    ledger.runs.create(Run(id="run_bad", employee_id="emp_1", task_id="t1", status=RunStatus.FAILED))
    ledger.recovery_actions.open(
        RecoveryAction(id="rec_1", source_task_id="t1", kind=RecoveryKind.STRANDED, max_attempts=3)
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "open_recovery"


# -- in_progress: continuity --------------------------------------------------


def test_in_progress_with_active_run_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.IN_PROGRESS)
    _running_run(ledger, "t1", lease=FUTURE)
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "active_run"


def test_in_progress_with_expired_lease_is_stalled(ledger: SqliteLedger, emp: Employee) -> None:
    # A running row whose lease has passed is NOT an action path (the beat stopped renewing).
    task = _task(ledger, TaskStatus.IN_PROGRESS)
    _running_run(ledger, "t1", lease=PAST)
    result = classify(task, ledger, now=NOW)
    assert result.stalled
    assert result.reason == "stranded_in_progress"


def test_in_progress_with_queued_continuation_is_healthy(
    ledger: SqliteLedger, emp: Employee
) -> None:
    task = _task(ledger, TaskStatus.IN_PROGRESS)
    _running_run(ledger, "t1", lease=PAST)  # dead run...
    ledger.wakes.enqueue(  # ...but a continuation is queued
        Wake(id="w1", employee_id="emp_1", reason=WakeReason.DEPS_RESOLVED, payload={"task_id": "t1"})
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "queued_continuation"


def test_in_progress_with_active_monitor_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.IN_PROGRESS)
    ledger.monitors.arm(
        Monitor(id="m1", task_id="t1", employee_id="emp_1", next_check_at=FUTURE)
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "active_monitor"


# -- in_review: the review path -----------------------------------------------


def test_in_review_with_pending_approval_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.IN_REVIEW)
    ledger.approvals.request(
        Approval(id="ap1", subject_kind=ApprovalSubjectKind.TASK, subject_id="t1", reason="sign off")
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "pending_approval"


def test_in_review_with_no_path_is_stalled(ledger: SqliteLedger, emp: Employee) -> None:
    # "Assign back to the same employee with a 'please review' comment" is not a structured path.
    task = _task(ledger, TaskStatus.IN_REVIEW)
    result = classify(task, ledger, now=NOW)
    assert result.stalled
    assert result.reason == "stranded_in_review"


def test_in_review_with_queued_wake_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    task = _task(ledger, TaskStatus.IN_REVIEW)
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="emp_1", reason=WakeReason.MESSAGE, payload={"task_id": "t1"})
    )
    assert classify(task, ledger, now=NOW).healthy


# -- blocked: surface the first stalled leaf ----------------------------------


def test_blocked_on_healthy_leaf_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    parent = _task(ledger, TaskStatus.BLOCKED, task_id="t1")
    _task(ledger, TaskStatus.IN_PROGRESS, task_id="t2")  # blocker, itself live
    _running_run(ledger, "t2", lease=FUTURE)
    ledger.dependencies.add("t1", "t2")
    result = classify(parent, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "healthy_blocker"


def test_blocked_on_stalled_leaf_surfaces_it(ledger: SqliteLedger, emp: Employee) -> None:
    parent = _task(ledger, TaskStatus.BLOCKED, task_id="t1")
    # blocker is a stranded todo (interrupted dispatch, nothing queued)
    _task(ledger, TaskStatus.TODO, task_id="t2")
    ledger.runs.create(Run(id="run_bad", employee_id="emp_1", task_id="t2", status=RunStatus.FAILED))
    ledger.dependencies.add("t1", "t2")
    result = classify(parent, ledger, now=NOW)
    assert result.stalled
    assert "t2" in result.reason


def test_blocked_on_never_dispatched_leaf_surfaces_it(ledger: SqliteLedger, emp: Employee) -> None:
    # The tinyvec scenario: the parent goal is `blocked` on a child stuck in `todo` that was NEVER
    # dispatched (no runs at all, no wake). Before the fix the leaf read "resting" healthy → the parent
    # read "healthy_blocker" → the goal hung forever. The leaf must now surface as the stalled blocker.
    parent = _task(ledger, TaskStatus.BLOCKED, task_id="t1")
    _task(ledger, TaskStatus.TODO, task_id="t2")  # never dispatched: no run, no wake
    ledger.dependencies.add("t1", "t2")
    result = classify(parent, ledger, now=NOW)
    assert result.stalled
    assert "t2" in result.reason


def test_blocked_with_open_recovery_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    from chorus.ledger._models import RecoveryAction, RecoveryKind

    task = _task(ledger, TaskStatus.BLOCKED)
    ledger.recovery_actions.open(
        RecoveryAction(id="rec_1", source_task_id="t1", kind=RecoveryKind.GRAPH_LIVENESS, max_attempts=3)
    )
    assert classify(task, ledger, now=NOW).healthy


def test_blocked_with_no_blocker_is_stalled(ledger: SqliteLedger, emp: Employee) -> None:
    # blocked but nothing names the blocker or owner → stalled (spec 02 §3 blocked).
    task = _task(ledger, TaskStatus.BLOCKED)
    result = classify(task, ledger, now=NOW)
    assert result.stalled
    assert result.reason == "blocked_no_blocker"


def test_blocked_with_a_live_wake_is_healthy(ledger: SqliteLedger, emp: Employee) -> None:
    # A parked manager (M3): once its children land, its blockers resolve but it stays `blocked` with a
    # queued `children_done` wake pending the integrate beat. That is healthy — about to be dispatched —
    # not a stalled leaf. (Without this, the recovery sweep strands the parent before it integrates.)
    task = _task(ledger, TaskStatus.BLOCKED)
    ledger.wakes.enqueue(
        Wake(id="w1", employee_id="emp_1", reason=WakeReason.CHILDREN_DONE, payload={"task_id": "t1"})
    )
    result = classify(task, ledger, now=NOW)
    assert result.healthy
    assert result.reason == "queued_wake"
