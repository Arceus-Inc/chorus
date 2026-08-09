"""The beat — one employee's ``dream.run_task`` invocation, landed to the ledger (spec 03 §3).

A beat is born from a claimed wake and dies on completion: rehydrate the employee, mint the run row
(``begin_execution`` — the execution lock the checkout already points at), call the one dream seam,
land the verdict, set the task's terminal status, release the lock, fire the downstream wakes, and
mark the wake done. dream is kept behind the :class:`~chorus.heartbeat._beat.BeatRunner` Protocol so
a beat is testable with a fake — no LLM, no worktree.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome, BeatRunner
from chorus.ledger import Ledger, Task
from chorus.ledger._models import (
    DodStatus,
    ExecutionMode,
    RecoveryKind,
    RunStatus,
    TaskStatus,
    WakeStatus,
)
from chorus.recovery import ReconcileReport, reconcile
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")


class _FakeBeat:
    """A stand-in :class:`BeatRunner` that records its call and returns a canned verdict."""

    def __init__(self, *, passed: bool, outcome: dict[str, object] | None = None) -> None:
        self._passed = passed
        self._outcome = outcome or {}
        self.calls: list[dict[str, object]] = []

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        self.calls.append({"task_id": task_id, "intent": intent, "observer": observer})
        return BeatOutcome(passed=self._passed, outcome=self._outcome, summary="done")


class _CannedBeat:
    """A :class:`BeatRunner` that returns a prebuilt :class:`BeatOutcome` (for the failure contract)."""

    def __init__(self, outcome: BeatOutcome) -> None:
        self._outcome = outcome

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        return self._outcome


class _CancellingBeat:
    """Cancel its task while the external call is in flight, then report usage."""

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        assert self._ledger.cancel_task(task_id)
        return BeatOutcome(
            passed=True,
            summary="finished after cancellation",
            cost_cents=17,
            model="gpt-test",
            input_tokens=11,
            output_tokens=7,
        )


class _WatchdogWinningBeat:
    """Reap its own in-flight run before returning a deliberately late outcome."""

    def __init__(self, ledger: Ledger, outcome: BeatOutcome) -> None:
        self._ledger = ledger
        self._outcome = outcome
        self.report: ReconcileReport | None = None

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: object = (),
        rubric: object = "",
        observer: object = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        assert run_id is not None
        self.report = reconcile(self._ledger, now=_NOW + timedelta(hours=1))
        return self._outcome


class _FakeWorkforce:
    """A minimal :class:`~chorus.workforce.Workforce` — only ``get`` is exercised by a beat."""

    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _wired(ledger: Ledger, beat: BeatRunner, *, eid: str = uid("e1")) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(Employee(id=eid, name=eid, role="engineer")),
        beat_runner=beat,
    )


def _setup_task(
    ledger: Ledger,
    *,
    tid: str = uid("t1"),
    eid: str = uid("e1"),
    run_id: str = uid("r1"),
    execution_mode: ExecutionMode = ExecutionMode.DELIVERY,
) -> Wake:
    """Mirror what the tick does before a beat: employee + assigned todo, checked out, wake claimed."""
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.tasks.submit(
        Task(
            id=tid,
            intent=f"do {tid}",
            assignee_employee_id=eid,
            execution_mode=execution_mode,
        )
    )
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    assert ledger.tasks.checkout(tid, employee_id=eid, run_id=run_id)
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"), employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid}
        )
    )
    (claimed,) = ledger.wakes.claim(limit=1)
    return claimed


async def test_passed_beat_marks_task_done(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.DONE


async def test_failed_beat_blocks_task(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


async def test_beat_mints_running_run_with_lease(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    run = ledger.runs.get(uid("r1"))
    assert run is not None
    assert run.task_id == uid("t1")
    assert run.wake_id == uid("w1")
    assert run.lease_expires_at is not None and run.lease_expires_at > _NOW
    assert run.status is RunStatus.SUCCEEDED  # finished by the time the beat returns


async def test_failed_beat_finishes_run_failed(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    run = ledger.runs.get(uid("r1"))
    assert run is not None
    assert run.status is RunStatus.FAILED


async def test_beat_releases_locks(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.checkout_run_id is None
    assert task.execution_run_id is None


async def test_beat_marks_wake_done(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    done = ledger.wakes.get(uid("w1"))
    assert done is not None
    assert done.status.value == "done"
    assert ledger.wakes.queued() == []


async def test_cancelled_task_does_not_start_a_claimed_beat(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    assert ledger.cancel_task(uid("t1"))

    beat = _FakeBeat(passed=True)
    await _wired(ledger, beat).run_beat(wake, run_id=uid("r1"), now=_NOW)

    assert beat.calls == []
    assert ledger.runs.get(uid("r1")) is None
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.CANCELLED


async def test_in_flight_cancellation_still_records_returned_usage(ledger: Ledger) -> None:
    wake = _setup_task(ledger)

    await _wired(ledger, _CancellingBeat(ledger)).run_beat(
        wake, run_id=uid("r1"), now=_NOW
    )

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.CANCELLED
    assert ledger.cost_events.spent_cents(uid("e1")) == 17
    events = ledger.cost_events.for_run(uid("r1"))
    assert len(events) == 1
    assert events[0].input_tokens == 11
    assert events[0].output_tokens == 7


async def test_watchdog_timeout_fences_late_success_effects(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    ledger.dod.create(uid("t1"), _command_verifier())
    outcome = BeatOutcome(
        passed=True,
        outcome={"late": True},
        summary="completed after watchdog timeout",
        cost_cents=19,
    )

    beat = _WatchdogWinningBeat(ledger, outcome)
    await _wired(ledger, beat).run_beat(wake, run_id=uid("r1"), now=_NOW)

    assert beat.report is not None
    assert beat.report.reaped_runs == [uid("r1")]
    assert beat.report.recovered == [uid("t1")]
    run = ledger.runs.get(uid("r1"))
    assert run is not None
    assert run.status is RunStatus.TIMED_OUT
    assert run.outcome == {}
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.checkout_run_id is None
    assert task.execution_run_id is None
    dod = ledger.dod.get_for_task(uid("t1"))
    assert dod is not None and dod.status is DodStatus.PENDING
    assert ledger.wakes.get(wake.id).status is WakeStatus.DONE  # type: ignore[union-attr]
    recovery_wakes = [
        queued
        for queued in ledger.wakes.queued()
        if queued.reason is WakeReason.RECOVERY
        and queued.payload.get("task_id") == uid("t1")
    ]
    assert len(recovery_wakes) == 1
    assert ledger.cost_events.for_run(uid("r1")) == []


async def test_watchdog_timeout_fences_late_error_recovery_effects(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    outcome = BeatOutcome(
        passed=False,
        disposition=BeatDisposition.ERRORED,
        outcome={"error": "RunTaskError('late')", "phase": "sprint"},
    )

    await _wired(ledger, _WatchdogWinningBeat(ledger, outcome)).run_beat(
        wake, run_id=uid("r1"), now=_NOW
    )

    assert ledger.runs.get(uid("r1")).status is RunStatus.TIMED_OUT  # type: ignore[union-attr]
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.IN_PROGRESS  # type: ignore[union-attr]
    assert ledger.recovery_actions.active_for_source(uid("t1")) is None


async def test_watchdog_timeout_fences_late_delegation_effects(ledger: Ledger) -> None:
    wake = _setup_task(ledger, execution_mode=ExecutionMode.DELEGATION)
    outcome = BeatOutcome(passed=True, summary="late delegation kickoff")

    await _wired(ledger, _WatchdogWinningBeat(ledger, outcome)).run_beat(
        wake, run_id=uid("r1"), now=_NOW
    )

    assert ledger.runs.get(uid("r1")).status is RunStatus.TIMED_OUT  # type: ignore[union-attr]
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.IN_PROGRESS  # type: ignore[union-attr]
    assert not [wake for wake in ledger.wakes.queued() if wake.reason is WakeReason.CHILDREN_DONE]


async def test_passed_beat_records_dod_verdict(ledger: Ledger) -> None:
    eid, tid = uid("e1"), uid("t1")
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.tasks.submit(Task(id=tid, intent="ship it", assignee_employee_id=eid))
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    ledger.dod.create(tid, _command_verifier())
    assert ledger.tasks.checkout(tid, employee_id=eid, run_id=uid("r1"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"), employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid}
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    sched = _wired(ledger, _FakeBeat(passed=True, outcome={"pr": "#7"}))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    dod = ledger.dod.get_for_task(tid)
    assert dod is not None
    assert dod.status is DodStatus.PASSED


async def test_passed_beat_fires_downstream_deps_resolved(ledger: Ledger) -> None:
    wake = _setup_task(ledger)  # t1 assigned to e1, checked out
    # A dependent t2 (assigned to e2) waits on t1 — completing t1 should wake e2.
    ledger.employees.create(Employee(id=uid("e2"), name=uid("e2"), role="engineer"))
    ledger.tasks.submit(Task(id=uid("t2"), intent="after t1", assignee_employee_id=uid("e2")))
    ledger.tasks.set_status(uid("t2"), TaskStatus.TODO)
    ledger.dependencies.add(uid("t2"), uid("t1"))
    sched = _wired(ledger, _FakeBeat(passed=True))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    downstream = ledger.wakes.queued(employee_id=uid("e2"))
    assert len(downstream) == 1
    assert downstream[0].reason is WakeReason.DEPS_RESOLVED
    assert downstream[0].payload["task_id"] == uid("t2")


async def test_failed_beat_fires_no_downstream(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    ledger.employees.create(Employee(id=uid("e2"), name=uid("e2"), role="engineer"))
    ledger.tasks.submit(Task(id=uid("t2"), intent="after t1", assignee_employee_id=uid("e2")))
    ledger.tasks.set_status(uid("t2"), TaskStatus.TODO)
    ledger.dependencies.add(uid("t2"), uid("t1"))
    sched = _wired(ledger, _FakeBeat(passed=False))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    assert ledger.wakes.queued(employee_id=uid("e2")) == []


async def test_beat_passes_task_intent_to_dream(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    beat = _FakeBeat(passed=True)
    sched = _wired(ledger, beat)
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)
    assert len(beat.calls) == 1
    assert beat.calls[0]["task_id"] == uid("t1")
    assert beat.calls[0]["intent"] == f"do {uid('t1')}"


async def test_delegated_beat_carries_parent_objective_context(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name=uid("e1"), role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("parent"), intent="Build SQLite click ingestion keyed by event id")
    )
    ledger.tasks.submit(
        Task(
            id=uid("child"),
            intent="Implement analytics.py and its dedicated tests",
            parent_id=uid("parent"),
            depth=1,
            assignee_employee_id=uid("e1"),
        )
    )
    ledger.tasks.set_status(uid("child"), TaskStatus.TODO)
    assert ledger.tasks.checkout(uid("child"), employee_id=uid("e1"), run_id=uid("r1"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id=uid("e1"),
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": uid("child")},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    beat = _FakeBeat(passed=True)

    await _wired(ledger, beat).run_beat(wake, run_id=uid("r1"), now=_NOW)

    intent = str(beat.calls[0]["intent"])
    assert intent == "Implement analytics.py and its dedicated tests"


async def test_errored_beat_strands_task_to_recovery(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    outcome = BeatOutcome(
        passed=False,
        disposition=BeatDisposition.ERRORED,
        outcome={"error": "RunTaskError('boom')", "phase": "sprint"},
    )
    sched = _wired(ledger, _CannedBeat(outcome))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED  # stranded, not a DoD failure
    assert task.assignee_employee_id == uid("e1")  # owner preserved
    run = ledger.runs.get(uid("r1"))
    assert run is not None and run.status is RunStatus.FAILED
    action = ledger.recovery_actions.active_for_source(uid("t1"))
    assert action is not None
    assert action.kind is RecoveryKind.STRANDED
    assert action.cause == "run_task_error"
    assert action.evidence["phase"] == "sprint"  # the phase names where the loop broke


async def test_errored_beat_records_no_dod_verdict(ledger: Ledger) -> None:
    # an engine fault is not a DoD verdict — the dod row must stay pending (never recorded failed).
    eid, tid = uid("e1"), uid("t1")
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    ledger.tasks.submit(Task(id=tid, intent="ship it", assignee_employee_id=eid))
    ledger.tasks.set_status(tid, TaskStatus.TODO)
    ledger.dod.create(tid, _command_verifier())
    assert ledger.tasks.checkout(tid, employee_id=eid, run_id=uid("r1"))
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"), employee_id=eid, reason=WakeReason.TASK_ASSIGNED, payload={"task_id": tid}
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    outcome = BeatOutcome(
        passed=False, disposition=BeatDisposition.ERRORED, outcome={"phase": "plan"}
    )
    await _wired(ledger, _CannedBeat(outcome)).run_beat(wake, run_id=uid("r1"), now=_NOW)
    dod = ledger.dod.get_for_task(tid)
    assert dod is not None
    assert dod.status is DodStatus.PENDING


async def test_errored_beat_releases_locks(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    outcome = BeatOutcome(
        passed=False, disposition=BeatDisposition.ERRORED, outcome={"phase": "plan"}
    )
    await _wired(ledger, _CannedBeat(outcome)).run_beat(wake, run_id=uid("r1"), now=_NOW)
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.checkout_run_id is None
    assert task.execution_run_id is None


async def test_cancelled_beat_returns_task_to_pre_beat_state(ledger: Ledger) -> None:
    wake = _setup_task(ledger)
    outcome = BeatOutcome(
        passed=False, disposition=BeatDisposition.CANCELLED, outcome={"cancelled": "budget"}
    )
    sched = _wired(ledger, _CannedBeat(outcome))
    await sched.run_beat(wake, run_id=uid("r1"), now=_NOW)

    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.TODO  # back to dispatchable, its pre-beat state
    assert task.checkout_run_id is None  # lock released
    run = ledger.runs.get(uid("r1"))
    assert run is not None and run.status is RunStatus.CANCELLED
    assert (
        ledger.recovery_actions.active_for_source(uid("t1")) is None
    )  # cancel opens no recovery card


def _command_verifier() -> object:
    from chorus.outcomes import Verifier

    return Verifier.command("pytest -q")
