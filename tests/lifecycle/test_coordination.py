"""Wake producers — assignment + messaging actually fire wakes (spec 03 §2, spec 01 Cluster G).

The two async-handoff producers: assigning a task wakes its new owner (``task_assigned``) and audits
the handoff (``ASSIGNED``); delivering a message wakes the recipient (``message``), coalesced to one
"check your mail" nudge. Each folds the durable write and the wake into one transaction.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Message, SqliteLedger, Task
from chorus.ledger._models import ActivityVerb, TaskStatus, WakeReason
from chorus.lifecycle import assign_task, deliver_message
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: SqliteLedger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


# -- assignment -----------------------------------------------------------------------------------


def test_assign_moves_to_todo_assigns_and_wakes(ledger: SqliteLedger) -> None:
    _emp(ledger, "e1")
    ledger.tasks.submit(Task(id="t1", intent="ship"))  # backlog, unassigned
    wake = assign_task(ledger, "t1", "e1", assigned_by="mgr")

    assert wake is not None
    assert wake.reason is WakeReason.TASK_ASSIGNED
    assert wake.employee_id == "e1"
    assert wake.payload["task_id"] == "t1"
    task = ledger.tasks.get("t1")
    assert task is not None
    assert task.status is TaskStatus.TODO
    assert task.assignee_employee_id == "e1"
    assert [w.id for w in ledger.wakes.queued(employee_id="e1")] == [wake.id]
    # the handoff is audited (closes the spec 08 §5 ASSIGNED verb)
    acts = ledger.activity.by_subject("task", "t1")
    assert [a.verb for a in acts] == [ActivityVerb.ASSIGNED]
    assert acts[0].actor_employee_id == "mgr"


def test_assign_unknown_task_returns_none(ledger: SqliteLedger) -> None:
    _emp(ledger, "e1")
    assert assign_task(ledger, "ghost", "e1") is None


def test_assign_terminal_task_returns_none(ledger: SqliteLedger) -> None:
    _emp(ledger, "e1")
    ledger.tasks.submit(Task(id="t1", intent="done thing", status=TaskStatus.DONE))
    assert assign_task(ledger, "t1", "e1") is None
    assert ledger.wakes.queued(employee_id="e1") == []  # no wake for an unassignable task


# -- messaging ------------------------------------------------------------------------------------


def test_deliver_message_persists_and_wakes_recipient(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    wake = deliver_message(
        ledger, Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="do X")
    )

    assert wake.reason is WakeReason.MESSAGE
    assert wake.employee_id == "rep"
    assert [m.id for m in ledger.messages.inbox("rep")] == ["m1"]
    assert [w.id for w in ledger.wakes.queued(employee_id="rep")] == [wake.id]


def test_message_wakes_coalesce_per_recipient(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    deliver_message(
        ledger, Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="a")
    )
    deliver_message(
        ledger, Message(id="m2", from_employee_id="mgr", to_employee_id="rep", body="b")
    )
    # both messages land in the inbox, but the recipient gets a single "check your mail" wake
    assert len(ledger.messages.inbox("rep")) == 2
    assert len(ledger.wakes.queued(employee_id="rep")) == 1
