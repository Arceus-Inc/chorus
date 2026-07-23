"""A budget-exhaustion timeout RESUMES rather than strands (resumption Slice B).

When a beat exhausts its wall-clock budget (a ``TimeoutError``) the work is unfinished, not wrong: the
worktree — and the durable ``TODO.md`` checklist ``todo_write`` left in it — persist, so the next beat
should re-dispatch the SAME task to the SAME employee and continue where it left off. This is distinct
from a DoD failure (needs-changes) and burns its own budget (``max_resume_attempts``), not the repair
budget. Past that budget, repeated exhaustion means the task is too big for one beat, so it strands for
a human (a later slice routes it to decompose).
"""

from __future__ import annotations

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


class _TimeoutBeat:
    """ERRORED with a TimeoutError-shaped fault for the first ``fail_times`` calls, then PASSED."""

    def __init__(self, *, fail_times: int) -> None:
        self._fail_times = fail_times
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
            # what dream raises when asyncio.wait_for(beat, timeout) trips — a hard, non-retryable fault
            return BeatOutcome(
                passed=False,
                disposition=BeatDisposition.ERRORED,
                outcome={"error": "TimeoutError()", "phase": None},
                retryable=False,
            )
        return BeatOutcome(passed=True, outcome={}, summary="ok")


class _FakeWorkforce:
    def __init__(self, *employees: Employee) -> None:
        self._by_id = {e.id: e for e in employees}

    def get(self, employee_id: str) -> Employee:
        return self._by_id[employee_id]


def _dispatch(ledger: Ledger, beat: _TimeoutBeat, *, max_resume_attempts: int = 2) -> Scheduler:
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
        max_resume_attempts=max_resume_attempts,
        max_concurrent_runs=1,
    )


async def test_budget_timeout_resumes_the_same_task_instead_of_stranding(
    ledger: Ledger,
) -> None:
    beat = _TimeoutBeat(fail_times=1)  # beat 1 times out; beat 2 resumes and finishes
    sched = _dispatch(ledger, beat)
    for _ in range(4):
        await sched.tick_once()
        await sched.drain()
        task = ledger.tasks.get(uid("t1"))
        assert task is not None
        # a timeout must NEVER strand while resume budget remains — it re-dispatches, not blocks
        if task.status is TaskStatus.DONE:
            break
        assert task.status is not TaskStatus.BLOCKED
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert beat.calls == 2  # beat 1 (timeout) + beat 2 (resumed → passed)
    assert task.status is TaskStatus.DONE
    assert task.assignee_employee_id == uid("e1")  # resumed by the SAME employee


async def test_repeated_timeout_strands_after_the_resume_budget(ledger: Ledger) -> None:
    beat = _TimeoutBeat(fail_times=99)  # never finishes — always times out
    sched = _dispatch(ledger, beat, max_resume_attempts=2)
    for _ in range(6):
        await sched.tick_once()
        await sched.drain()
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert beat.calls == 3  # 1 attempt + 2 resumes, then stranded (bounded)
    assert task.status is TaskStatus.BLOCKED
