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

from chorus.ledger import Ledger, Task, TaskStatus, Wake
from chorus.ledger._models import (
    RecoveryAction,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryStatus,
    Run,
    RunStatus,
    WakeReason,
    WakeStatus,
)
from chorus.recovery import _reap_orphaned_runs, reconcile
from chorus.testing import uid
from chorus.workforce import Employee

NOW = datetime(2026, 6, 15, 12, 0, 0, tzinfo=UTC)
FUTURE = NOW + timedelta(seconds=60)
PAST = NOW - timedelta(seconds=60)


@pytest.fixture(autouse=True)
def emp(ledger: Ledger) -> Employee:
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))


def _task(
    ledger: Ledger,
    status: TaskStatus,
    *,
    task_id: str = uid("t1"),
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
    ledger: Ledger,
    status: RunStatus,
    *,
    run_id: str | None = None,
    task_id: str = uid("t1"),
    lease: datetime | None = None,
    wake_id: str | None = None,
) -> Run:
    return ledger.runs.create(
        Run(
            id=run_id or uid(f"run_{status.value}"),
            employee_id="emp_1",
            task_id=task_id,
            wake_id=wake_id,
            status=status,
            lease_expires_at=lease,
        )
    )


# -- failed-prerequisite cascade (a rejected child must not deadlock the subtree) --


def _child(ledger: Ledger, task_id: str, status: TaskStatus) -> Task:
    return ledger.tasks.submit(
        Task(
            id=task_id,
            intent=task_id,
            status=status,
            assignee_employee_id="emp_1",
            parent_id=uid("goal"),
        )
    )


def test_cascade_cancels_a_task_blocked_by_a_failed_prerequisite(ledger: Ledger) -> None:
    """A dependent whose blocker is terminal-but-not-``done`` (rejected/cancelled) can never run.

    reconcile cancels it so the subtree terminalizes and the manager gets a ``children_done`` beat to
    react (re-submit the failed branch) — instead of the whole goal deadlocking on a stuck ``todo``.
    """
    ledger.employees.create(Employee(id="moe", name="moe", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("goal"),
            intent=uid("goal"),
            status=TaskStatus.BLOCKED,
            assignee_employee_id="moe",
        )
    )
    _child(
        ledger, uid("A"), TaskStatus.REJECTED
    )  # the reviewer blocked the impl (terminal, not done)
    _child(ledger, uid("B"), TaskStatus.DONE)
    c = _child(ledger, uid("C"), TaskStatus.TODO)  # depends on A → its blocker can never resolve
    ledger.dependencies.add(c.id, uid("A"))

    reconcile(ledger, now=NOW)

    assert (
        ledger.tasks.get(uid("C")).status is TaskStatus.CANCELLED
    )  # the doomed dependent is cancelled
    woken = [w for w in ledger.wakes.queued() if w.payload.get("task_id") == uid("goal")]
    assert [w.reason for w in woken] == [WakeReason.CHILDREN_DONE]  # manager gets its react beat


def _open_recovery(ledger: Ledger, task_id: str, owner: str = "emp_1") -> None:
    ledger.recovery_actions.open(
        RecoveryAction(
            id=uid(f"rec_{task_id}"),
            source_task_id=task_id,
            kind=RecoveryKind.STALE_RUN_WATCHDOG,
            owner_employee_id=owner,
            cause="run_task_error",
            fingerprint="x",
            next_action="fix",
        )
    )


def test_stranded_child_terminalizes_so_the_parent_can_integrate(ledger: Ledger) -> None:
    """A child stranded on a recovery card (auto-recovery exhausted) would block its parent's integration
    forever with no human to clear it. reconcile terminalizes it (rejected) so the manager integrates and
    reacts — the autonomous org self-heals instead of deadlocking on a dead child."""
    ledger.employees.create(Employee(id="moe", name="moe", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("goal"),
            intent=uid("goal"),
            status=TaskStatus.BLOCKED,
            assignee_employee_id="moe",
        )
    )
    _child(ledger, uid("A"), TaskStatus.DONE)
    _child(ledger, uid("C"), TaskStatus.BLOCKED)
    _open_recovery(ledger, uid("C"))  # its retries are spent; only a human could move it

    reconcile(ledger, now=NOW)

    assert ledger.tasks.get(uid("C")).status is TaskStatus.REJECTED  # type: ignore[union-attr]
    woken = [w for w in ledger.wakes.queued() if w.payload.get("task_id") == uid("goal")]
    assert [w.reason for w in woken] == [WakeReason.CHILDREN_DONE]  # manager gets its react beat


def test_stranded_top_level_task_keeps_escalating_to_a_human(ledger: Ledger) -> None:
    """A stranded *top-level* task (no parent) is a human's to resolve — it stays blocked, not auto-killed."""
    _task(ledger, TaskStatus.BLOCKED, task_id=uid("solo"))
    _open_recovery(ledger, uid("solo"))

    reconcile(ledger, now=NOW)

    assert ledger.tasks.get(uid("solo")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]


def test_cascade_leaves_a_task_with_a_still_pending_blocker_alone(ledger: Ledger) -> None:
    """Only a *failed* prerequisite cascades — a blocker still in flight just keeps the dependent waiting."""
    ledger.employees.create(Employee(id="moe", name="moe", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("goal"),
            intent=uid("goal"),
            status=TaskStatus.BLOCKED,
            assignee_employee_id="moe",
        )
    )
    _child(ledger, uid("A"), TaskStatus.IN_PROGRESS)  # still working — not a failure
    c = _child(ledger, uid("C"), TaskStatus.TODO)
    ledger.dependencies.add(c.id, uid("A"))

    reconcile(ledger, now=NOW)

    assert (
        ledger.tasks.get(uid("C")).status is TaskStatus.TODO
    )  # untouched — its blocker may still succeed


# -- §7 step 1: reap orphaned running runs (lease passed) ----------------------


def test_reap_orphaned_running_run_releases_locks(ledger: Ledger) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id=uid("run_dead"),
        execution_run_id=uid("run_dead"),
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("wake_dead"),
            employee_id="emp_1",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": uid("t1")},
        )
    )
    (claimed,) = ledger.wakes.claim(limit=1)
    _run(
        ledger,
        RunStatus.RUNNING,
        run_id=uid("run_dead"),
        lease=PAST,
        wake_id=claimed.id,
    )
    ledger.wakes.assign_run(claimed.id, uid("run_dead"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("wake_unrelated"),
            employee_id="emp_1",
            reason=WakeReason.MESSAGE,
            payload={"task_id": uid("other")},
        )
    )

    report = reconcile(ledger, now=NOW)

    assert uid("run_dead") in report.reaped_runs
    assert report.recovered == [uid("t1")]
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.checkout_run_id is None  # crash recovery: the lock is released
    assert task.execution_run_id is None
    reaped = ledger.runs.get(uid("run_dead"))
    assert reaped is not None
    assert reaped.status is RunStatus.TIMED_OUT
    assert ledger.wakes.get(claimed.id).status is WakeStatus.DONE  # type: ignore[union-attr]
    assert ledger.wakes.get(uid("wake_unrelated")).status is WakeStatus.QUEUED  # type: ignore[union-attr]
    recovery_wakes = [
        wake
        for wake in ledger.wakes.queued()
        if wake.reason is WakeReason.RECOVERY and wake.payload.get("task_id") == uid("t1")
    ]
    assert len(recovery_wakes) == 1


def test_late_completion_cannot_overwrite_a_reaped_timeout(ledger: Ledger) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id=uid("run_dead"),
        execution_run_id=uid("run_dead"),
    )
    _run(ledger, RunStatus.RUNNING, run_id=uid("run_dead"), lease=PAST)

    report = reconcile(ledger, now=NOW)

    assert report.reaped_runs == [uid("run_dead")]
    assert ledger.runs.finish(uid("run_dead"), RunStatus.SUCCEEDED) is False
    reaped = ledger.runs.get(uid("run_dead"))
    assert reaped is not None
    assert reaped.status is RunStatus.TIMED_OUT


def test_stale_reaper_observation_that_loses_to_completion_keeps_locks(
    ledger: Ledger, monkeypatch: pytest.MonkeyPatch
) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id=uid("run_dead"),
        execution_run_id=uid("run_dead"),
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("wake_dead"),
            employee_id="emp_1",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": uid("t1")},
        )
    )
    (claimed,) = ledger.wakes.claim(limit=1)
    _run(
        ledger,
        RunStatus.RUNNING,
        run_id=uid("run_dead"),
        lease=PAST,
        wake_id=claimed.id,
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("wake_unrelated"),
            employee_id="emp_1",
            reason=WakeReason.MESSAGE,
            payload={"task_id": uid("other")},
        )
    )
    stale_observation = ledger.runs.running_with_expired_lease(NOW)

    assert ledger.runs.finish(uid("run_dead"), RunStatus.SUCCEEDED)

    def expired_at(_: datetime) -> list[Run]:
        return stale_observation

    monkeypatch.setattr(ledger.runs, "running_with_expired_lease", expired_at)
    assert _reap_orphaned_runs(ledger, now=NOW) == []

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.checkout_run_id == uid("run_dead")
    assert task.execution_run_id == uid("run_dead")
    assert ledger.wakes.get(claimed.id).status is WakeStatus.CLAIMED  # type: ignore[union-attr]
    assert ledger.wakes.get(uid("wake_unrelated")).status is WakeStatus.QUEUED  # type: ignore[union-attr]


def test_running_run_with_future_lease_is_not_reaped(ledger: Ledger) -> None:
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        checkout_run_id=uid("run_live"),
        execution_run_id=uid("run_live"),
    )
    _run(ledger, RunStatus.RUNNING, run_id=uid("run_live"), lease=FUTURE)

    report = reconcile(ledger, now=NOW)

    assert report.reaped_runs == []
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.checkout_run_id == uid("run_live")  # live owner, untouched
    assert uid("t1") not in report.recovered  # an active run is a live path


# -- §9 mode a: stranded todo -> one assignment-recovery wake ------------------


def test_stranded_todo_enqueues_one_assignment_recovery_wake(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    report = reconcile(ledger, now=NOW)

    assert uid("t1") in report.recovered
    wakes = ledger.wakes.active_for_employee("emp_1")
    assert len(wakes) == 1
    wake = wakes[0]
    assert wake.reason is WakeReason.RECOVERY
    assert wake.payload["kind"] == "assignment_recovery"
    assert wake.payload["task_id"] == uid("t1")
    # The owner is preserved — never auto-reassigned (spec 02 §8).
    assert wake.employee_id == "emp_1"
    # Tier 1 only: the task stays todo, no recovery card yet.
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.TODO
    assert ledger.recovery_actions.active_for_source(uid("t1")) is None


def test_recovery_never_reassigns_to_a_different_employee(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("emp_2"), name="bob", role="engineer"))
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)

    assert ledger.wakes.active_for_employee(uid("emp_2")) == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_recovery_wake_is_idempotent_while_pending(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)
    second = reconcile(ledger, now=NOW)

    # The pending wake is itself a live path, so the second pass is a no-op.
    assert second.recovered == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_recovery_wake_carries_the_cheap_lane_guards(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)

    wake = ledger.wakes.active_for_employee("emp_1")[0]
    assert wake.payload["lane"] == "cheap"
    assert wake.payload["allow_deliverable_work"] is False
    assert wake.payload["allow_document_updates"] is False
    assert wake.payload["resume_requires_normal"] is True


# -- §9 mode b: stranded in_progress -> one continuation wake ------------------


def test_stranded_in_progress_enqueues_one_continuation_wake(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.IN_PROGRESS)
    _run(ledger, RunStatus.FAILED)  # the live run disappeared

    report = reconcile(ledger, now=NOW)

    assert uid("t1") in report.recovered
    wakes = ledger.wakes.active_for_employee("emp_1")
    assert len(wakes) == 1
    assert wakes[0].payload["kind"] == "continuation"
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS  # tier 1: still in_progress


# -- ladder exhaustion: delivered wake + still stranded -> blocked + recovery --


def _deliver_recovery_wake(ledger: Ledger) -> None:
    [wake] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(wake.id)


def test_delivered_recovery_wake_still_stranded_escalates_to_blocked(
    ledger: Ledger,
) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    reconcile(ledger, now=NOW)  # tier 1: enqueue one wake
    _deliver_recovery_wake(ledger)  # the employee ran it and it's still stranded
    report = reconcile(ledger, now=NOW)  # tier 2: escalate

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED
    action = ledger.recovery_actions.active_for_source(uid("t1"))
    assert action is not None
    assert action.id in report.opened
    assert action.kind is RecoveryKind.STRANDED
    assert action.owner_employee_id == "emp_1"  # owner preserved
    assert action.status is RecoveryStatus.ACTIVE


def test_open_recovery_is_a_live_path_and_is_not_reopened(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)
    reconcile(ledger, now=NOW)
    _deliver_recovery_wake(ledger)
    reconcile(ledger, now=NOW)  # escalates -> blocked + recovery
    first = ledger.recovery_actions.active_for_source(uid("t1"))

    third = reconcile(ledger, now=NOW)  # the open recovery IS a live path

    assert third.opened == []
    again = ledger.recovery_actions.active_for_source(uid("t1"))
    assert first is not None and again is not None
    assert again.id == first.id  # exact-once: no duplicate card


# -- in_review stall: no dispatch to retry -> open a recovery card directly ----


def test_stranded_in_review_opens_a_recovery_directly(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.IN_REVIEW)

    report = reconcile(ledger, now=NOW)

    action = ledger.recovery_actions.active_for_source(uid("t1"))
    assert action is not None
    assert action.id in report.opened
    assert action.owner_employee_id == "emp_1"
    assert report.recovered == []  # no retry wake — there's no dispatch to resume
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.IN_REVIEW  # the open card is the live path


# -- §6 source-aware folding: source went terminal -> fold the alert -----------


def test_open_recovery_is_folded_when_source_becomes_terminal(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.DONE)
    ledger.recovery_actions.open(
        RecoveryAction(
            id=uid("rec_stale"),
            source_task_id=uid("t1"),
            kind=RecoveryKind.STRANDED,
            owner_employee_id="emp_1",
            cause="stranded_todo",
            fingerprint="recovery",
        )
    )

    report = reconcile(ledger, now=NOW)

    assert uid("rec_stale") in report.folded
    action = ledger.recovery_actions.get(uid("rec_stale"))
    assert action is not None
    assert action.status is RecoveryStatus.FOLDED  # folded, not resolved (source self-resolved)
    assert action.outcome is RecoveryOutcome.FALSE_POSITIVE
    assert ledger.recovery_actions.active_for_source(uid("t1")) is None


# -- idempotency & non-interference -------------------------------------------


def test_reconcile_is_idempotent(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO)
    _run(ledger, RunStatus.FAILED)

    first = reconcile(ledger, now=NOW)
    second = reconcile(ledger, now=NOW)

    assert uid("t1") in first.recovered
    assert second.recovered == []
    assert second.opened == []
    assert second.folded == []
    assert second.reaped_runs == []
    assert len(ledger.wakes.active_for_employee("emp_1")) == 1


def test_healthy_tasks_are_left_untouched(ledger: Ledger) -> None:
    _task(ledger, TaskStatus.TODO, task_id=uid("resting"))  # no interrupted run -> healthy
    _task(
        ledger,
        TaskStatus.IN_PROGRESS,
        task_id=uid("human"),
        assignee_employee_id=None,
        assignee_user_id=uid("u_1"),
    )
    _task(ledger, TaskStatus.DONE, task_id=uid("done"))

    report = reconcile(ledger, now=NOW)

    assert report.recovered == []
    assert report.opened == []
    assert ledger.wakes.active_for_employee("emp_1") == []
