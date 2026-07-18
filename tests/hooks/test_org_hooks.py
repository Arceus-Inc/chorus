"""Org hooks — deterministic reactions to durable org events (free-run checklist: hooks).

The third leg beside routines (time-driven) and wakes (dispatch): a hook reads durable state
each pulse and takes a bounded, idempotent action in code — no model call, no veto power over
beats. The first built-in is the delegatory message hook: an unread INSTRUCTION message becomes
a real todo task for its recipient (fingerprinted by message id, so re-runs are no-ops), and
the message is consumed — work lands on the board instead of dying in an inbox.
"""

from __future__ import annotations

import uuid

import pytest

from chorus.hooks import default_org_hooks, run_org_hooks
from chorus.ledger import Ledger, Message, MessageKind, OriginKind, Task, TaskStatus
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _seed(ledger: Ledger) -> str:
    ledger.employees.create(Employee(id="mia", name="Mia", role="pm"))
    ledger.employees.create(Employee(id="rex", name="Rex", role="backend_engineer"))
    thread = ledger.tasks.submit(
        Task(id=str(uuid.uuid4()), intent="parent thread", assignee_employee_id="mia",
             goal_id=None)
    )
    return thread.id


def test_instruction_message_becomes_a_task_idempotently(ledger: Ledger) -> None:
    thread_id = _seed(ledger)
    message = ledger.messages.send(
        Message(
            id=str(uuid.uuid4()),
            from_employee_id="mia",
            to_employee_id="rex",
            task_id=thread_id,
            body="Please add retry logic to the uploader and cover it with a test.",
            kind=MessageKind.INSTRUCTION,
        )
    )

    fired = run_org_hooks(ledger, default_org_hooks())
    assert fired  # something acted

    created = ledger.tasks.find_by_origin(OriginKind.MANUAL, f"message:{message.id}")
    assert created is not None
    assert created.assignee_employee_id == "rex"
    assert created.status is TaskStatus.TODO
    assert "retry logic" in created.intent
    assert created.parent_id is None  # a fresh work item, not a delegation child
    # consumed: the inbox nudge is spent; the thread keeps the message
    assert all(m.id != message.id for m in ledger.messages.inbox("rex"))

    # Idempotent: a second pulse creates nothing new.
    run_org_hooks(ledger, default_org_hooks())
    tasks = [t for t in ledger.tasks.all() if t.origin_fingerprint == f"message:{message.id}"]
    assert len(tasks) == 1


def test_non_instruction_messages_are_left_alone(ledger: Ledger) -> None:
    thread_id = _seed(ledger)
    ledger.messages.send(
        Message(
            id=str(uuid.uuid4()),
            from_employee_id="mia",
            to_employee_id="rex",
            task_id=thread_id,
            body="nice work on the uploader!",
            kind=MessageKind.FYI,
        )
    )
    run_org_hooks(ledger, default_org_hooks())
    assert all(t.origin_fingerprint.startswith("message:") is False for t in ledger.tasks.all() if t.intent != "parent thread")
    assert len(ledger.messages.inbox("rex")) == 1  # FYI stays for the beat brief


def test_a_crashing_hook_never_kills_the_pulse(ledger: Ledger) -> None:
    _seed(ledger)

    def bomb(ledger_: Ledger) -> int:
        raise RuntimeError("hook bug")

    fired = run_org_hooks(ledger, (bomb, *default_org_hooks()))
    assert fired >= 0  # the pulse survived the crashing hook


@pytest.mark.asyncio
async def test_the_pulse_runs_org_hooks(ledger: Ledger) -> None:
    """The scheduler's pulse fires hooks after cron — reactions need no extra process."""
    from chorus.heartbeat import Scheduler
    from chorus.roles import RoleRegistry, default_roles
    from chorus.workforce import LedgerWorkforce

    thread_id = _seed(ledger)
    message = ledger.messages.send(
        Message(
            id=str(uuid.uuid4()),
            from_employee_id="mia",
            to_employee_id="rex",
            task_id=thread_id,
            body="Ship the retry patch.",
            kind=MessageKind.INSTRUCTION,
        )
    )

    class _NeverBeat:
        async def run_task(self, **_: object) -> None:
            raise AssertionError("no beat should dispatch in this tick")

    class _Factory:
        def runner_for(self, employee: object, *, task_id: str) -> object:
            return _NeverBeat()

    sched = Scheduler(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        beat_runner_for=_Factory(),  # type: ignore[arg-type]
        roles=RoleRegistry.from_plugins(default_roles()),
        max_concurrent_runs=0,  # hooks fire even when dispatch is saturated
    )
    await sched.tick_once()

    assert ledger.tasks.find_by_origin(OriginKind.MANUAL, f"message:{message.id}") is not None
