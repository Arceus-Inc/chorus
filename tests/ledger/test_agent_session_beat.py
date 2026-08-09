"""The beat ↔ agent_session bridge: chorus meters the thread, dream remembers it.

What this pins after the handle-only rescope:

- A beat opens one handle row per task and meters its spend onto it.
- The row is reused across beats, so the dream session key stays stable.
- The beat intent is *not* stuffed with prior transcript. Continuity is the key
  chorus hands back to dream, not a summary of the conversation replayed into
  the next prompt.
"""

from __future__ import annotations

import json

import pytest

from chorus.heartbeat import Scheduler, Wake, WakeReason
from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.ledger import (
    Ledger,
    Task,
    TaskStatus,
    begin_beat_session,
    dream_session_key_for_task,
    persist_beat_account,
)
from chorus.ledger._agent_session_store import ensure_open_session
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


class _Beat:
    def __init__(self, *, passed: bool = True) -> None:
        self.intents: list[str] = []
        self._passed = passed

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
        self.intents.append(intent)
        raw = json.dumps({"kind": "role.text", "text": f"handled:{intent[:24]}"})
        return BeatOutcome(
            passed=self._passed,
            disposition=BeatDisposition.PASSED if self._passed else BeatDisposition.DOD_FAILED,
            summary="ok" if self._passed else "not yet",
            raw_record=raw,
            model="test-model",
            input_tokens=10,
            output_tokens=5,
            cost_cents=3,
        )


def _employee_with_task(ledger: Ledger, intent: str) -> tuple[str, str]:
    emp = "ada"
    task_id = uid("t-session")
    ledger.employees.create(Employee(id=emp, name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(id=task_id, intent=intent, status=TaskStatus.TODO, assignee_employee_id=emp)
    )
    return emp, task_id


def _scheduler(ledger: Ledger, beat: _Beat) -> Scheduler:
    return Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner=beat,
        roles=RoleRegistry.from_plugins(default_roles()),
        max_concurrent_runs=1,
    )


async def _wake_and_run(
    ledger: Ledger, sched: Scheduler, *, emp: str, task_id: str, wake: str = "w1"
) -> None:
    ledger.wakes.enqueue(
        Wake(
            id=uid(wake),
            employee_id=emp,
            reason=WakeReason.MANUAL,
            payload={"task_id": task_id},
        )
    )
    await sched.tick_once()
    await sched.drain()


async def test_beat_meters_spend_onto_the_task_handle_row(ledger: Ledger) -> None:
    emp, task_id = _employee_with_task(ledger, "fix auth")
    ledger.dod.create(task_id, Verifier.command("true"))
    beat = _Beat()

    await _wake_and_run(ledger, _scheduler(ledger, beat), emp=emp, task_id=task_id)

    session = ledger.agent_sessions.latest_for_task(task_id)
    assert session is not None
    assert session.dream_session_key == dream_session_key_for_task(task_id)
    assert session.cost.input_tokens >= 10
    assert session.cost.output_tokens >= 5


async def test_handle_row_is_reused_so_the_dream_key_stays_stable(ledger: Ledger) -> None:
    """Two beats on unfinished work share one row — and so one dream thread.

    The beat falls short of its DoD, which is the case that matters: the task
    stays open, the next beat has to land on the same conversation, and a new
    row here would silently give it a blank one.
    """
    emp, task_id = _employee_with_task(ledger, "keep going")
    beat = _Beat(passed=False)
    sched = _scheduler(ledger, beat)

    await _wake_and_run(ledger, sched, emp=emp, task_id=task_id, wake="w1")
    first = ledger.agent_sessions.get_open_for_task(task_id)
    await _wake_and_run(ledger, sched, emp=emp, task_id=task_id, wake="w2")
    second = ledger.agent_sessions.get_open_for_task(task_id)

    assert first is not None and second is not None
    assert first.id == second.id
    # Spend accumulates on the one row rather than restarting per beat.
    assert second.cost.input_tokens > first.cost.input_tokens


async def test_beat_intent_carries_no_replayed_transcript(ledger: Ledger) -> None:
    """The prompt is the task, not a retelling of the last conversation.

    Before the rescope chorus formatted prior messages and tool results into the
    intent because dream had no way to reload a thread. dream resumes its own
    session now, so anything we prepend here would be the conversation twice.
    """
    emp, task_id = _employee_with_task(ledger, "continue work")
    session = ensure_open_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_session_key_for_task(task_id),
        model="",
        run_id=None,
    )
    persist_beat_account(ledger, session.id, input_tokens=40, output_tokens=9)

    beat = _Beat()
    await _wake_and_run(ledger, _scheduler(ledger, beat), emp=emp, task_id=task_id)

    assert beat.intents
    assert "Prior session transcript" not in beat.intents[0]
    assert "continue work" in beat.intents[0]


def test_begin_beat_session_binds_working_dir(ledger: Ledger) -> None:
    emp, task_id = _employee_with_task(ledger, "ship it")
    session = begin_beat_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        run_id=None,
        working_dir="/srv/worktrees/ada",
    )
    assert session.working_dir == "/srv/worktrees/ada"


def test_ensure_open_session_after_seal_reuses_dream_key(ledger: Ledger) -> None:
    """A sealed handle must not block the next open row with the same dream key."""
    emp, task_id = _employee_with_task(ledger, "again")
    dream_key = dream_session_key_for_task(task_id)
    first = ensure_open_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_key,
        model="",
        run_id=None,
    )
    ledger.agent_sessions.seal(first.id)
    second = ensure_open_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_key,
        model="",
        run_id=None,
    )
    assert second.id != first.id
    assert second.dream_session_key == dream_key
    assert second.status.value == "open"


def test_dream_session_key_is_a_usable_path_segment() -> None:
    """dream names a sidecar directory after the scope and rejects ``:`` there.

    A colon separator here failed every live beat with an "unsafe task_id"
    raised deep inside dream's engine construction, so the shape of this key is
    load-bearing rather than cosmetic.
    """
    key = dream_session_key_for_task("2f1c-abc")
    assert ":" not in key
    assert key == "task-2f1c-abc"


async def test_persist_beat_account_clears_a_previous_failure(ledger: Ledger) -> None:
    """A clean beat proves the thread usable, so the recorded reason goes away."""
    emp, task_id = _employee_with_task(ledger, "recover")
    session = ensure_open_session(
        ledger,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_session_key_for_task(task_id),
        model="",
        run_id=None,
    )
    ledger.agent_sessions.record_error(session.id, "working_dir_mismatch")
    assert ledger.agent_sessions.get(session.id).last_error == "working_dir_mismatch"  # type: ignore[union-attr]

    persist_beat_account(ledger, session.id, input_tokens=1)

    refreshed = ledger.agent_sessions.get(session.id)
    assert refreshed is not None
    assert refreshed.last_error is None
