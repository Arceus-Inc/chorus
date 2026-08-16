"""A transient (retryable) beat fault auto-retries before stranding the task (spec 05 §5).

A ``*HeadParseError`` blip — the model emitting unparseable structured output — is marked
``retryable`` by the adapter. The scheduler re-runs such a beat up to ``transient_retries`` times
before it strands the task onto the recovery ladder. A non-retryable engine fault strands on the
first fault, with no retry.
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import (
    Scheduler,
    SessionRecoveryAction,
    SessionRecoveryNotice,
    SessionRecoveryReason,
    Wake,
    WakeReason,
)
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import Ledger, RunStatus, Task, TaskStatus
from chorus.ledger._agent_session_store import ensure_open_session
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


class _FlakyBeat:
    """ERRORED for the first ``fail_times`` calls, then PASSED — records its call count."""

    def __init__(
        self,
        *,
        fail_times: int,
        retryable: bool = True,
        session_recovery: SessionRecoveryNotice | None = None,
        error_after_failures: Exception | None = None,
    ) -> None:
        self._fail_times = fail_times
        self._retryable = retryable
        self._session_recovery = session_recovery
        self._error_after_failures = error_after_failures
        self.calls = 0

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
        self.calls += 1
        if self.calls <= self._fail_times:
            return BeatOutcome(
                passed=False,
                disposition=BeatDisposition.ERRORED,
                outcome={"error": "PlannerHeadParseError('missing <spec>')", "phase": None},
                retryable=self._retryable,
                session_recovery=self._session_recovery,
            )
        if self._error_after_failures is not None:
            raise self._error_after_failures
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _dispatch(ledger: Ledger, beat: _FlakyBeat, *, transient_retries: int = 2) -> Scheduler:
    employee = ledger.employees.create(Employee(id=uid("e1"), name=uid("e1"), role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="x", status=TaskStatus.TODO, assignee_employee_id=uid("e1"))
    )
    ledger.wakes.enqueue(
        Wake(
            id=uid("w1"),
            employee_id=uid("e1"),
            reason=WakeReason.MANUAL,
            payload={"task_id": uid("t1")},
        )
    )
    return Scheduler(
        ledger=ledger,
        workforce=_FakeWorkforce(employee),
        beat_runner=beat,
        transient_retries=transient_retries,
        max_concurrent_runs=1,
    )


async def test_retryable_fault_retries_until_it_passes(ledger: Ledger) -> None:
    beat = _FlakyBeat(fail_times=2)  # two blips, then clean
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 3  # 1 attempt + 2 retries
    assert ledger.runs.for_task(uid("t1"))[-1].status is RunStatus.SUCCEEDED
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.DONE  # type: ignore[union-attr]


async def test_retry_success_persists_recovery_from_the_failed_attempt(ledger: Ledger) -> None:
    beat = _FlakyBeat(
        fail_times=1,
        session_recovery=SessionRecoveryNotice(
            role="generator",
            session_id="fresh-session",
            requested_session_id="stale-session",
            reason=SessionRecoveryReason.CORRUPT,
            action=SessionRecoveryAction.RESUME,
            snapshot_preserved=True,
        ),
    )
    sched = _dispatch(ledger, beat, transient_retries=1)

    await sched.tick_once()
    await sched.drain()

    assert beat.calls == 2
    session = ledger.agent_sessions.latest_for_task(uid("t1"))
    assert session is not None
    assert session.last_error == SessionRecoveryReason.CORRUPT.value


async def test_retry_raise_persists_recovery_on_the_original_session(ledger: Ledger) -> None:
    beat = _FlakyBeat(
        fail_times=1,
        session_recovery=SessionRecoveryNotice(
            role="generator",
            session_id="fresh-session",
            requested_session_id="stale-session",
            reason=SessionRecoveryReason.SCHEMA_MISMATCH,
            action=SessionRecoveryAction.RESET,
            snapshot_preserved=True,
        ),
        error_after_failures=RuntimeError("retry attempt crashed"),
    )
    sched = _dispatch(ledger, beat, transient_retries=1)
    original = ensure_open_session(
        ledger,
        employee_id=uid("e1"),
        task_id=uid("t1"),
        model="",
        run_id=None,
    )

    await sched.tick_once()
    await sched.drain()

    assert beat.calls == 2
    refreshed = ledger.agent_sessions.get(original.id)
    assert refreshed is not None
    assert refreshed.id == original.id
    assert refreshed.last_error == SessionRecoveryReason.SCHEMA_MISMATCH.value
    assert ledger.agent_sessions.latest_for_task(uid("t1")) == refreshed
    assert ledger.runs.for_task(uid("t1"))[-1].status is RunStatus.FAILED
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.BLOCKED


async def test_retryable_fault_strands_after_the_budget(ledger: Ledger) -> None:
    beat = _FlakyBeat(fail_times=99)  # never recovers
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 3  # capped at 1 + 2 retries
    assert ledger.runs.for_task(uid("t1"))[-1].status is RunStatus.FAILED
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]


async def test_non_retryable_fault_is_not_retried(ledger: Ledger) -> None:
    beat = _FlakyBeat(fail_times=99, retryable=False)
    sched = _dispatch(ledger, beat, transient_retries=2)
    await sched.tick_once()
    await sched.drain()
    assert beat.calls == 1  # stranded on the first fault, no retry
    assert ledger.tasks.get(uid("t1")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]
