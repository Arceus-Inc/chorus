"""Wake producers — assignment + messaging actually fire wakes (spec 03 §2, spec 01 Cluster G).

The two async-handoff producers: assigning a task wakes its new owner (``task_assigned``) and audits
the handoff (``ASSIGNED``); delivering a message wakes the recipient (``message``), coalesced to one
"check your mail" nudge. Each folds the durable write and the wake into one transaction.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger, Message, Task
from chorus.ledger._models import ActivityVerb, TaskStatus, WakeReason
from chorus.lifecycle import assign_task, deliver_message
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


# -- assignment -----------------------------------------------------------------------------------


def test_assign_moves_to_todo_assigns_and_wakes(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship"))  # backlog, unassigned
    wake = assign_task(ledger, uid("t1"), uid("e1"), assigned_by="mgr")

    assert wake is not None
    assert wake.reason is WakeReason.TASK_ASSIGNED
    assert wake.employee_id == uid("e1")
    assert wake.payload["task_id"] == uid("t1")
    task = ledger.tasks.get(uid("t1"))
    assert task is not None
    assert task.status is TaskStatus.TODO
    assert task.assignee_employee_id == uid("e1")
    assert [w.id for w in ledger.wakes.queued(employee_id=uid("e1"))] == [wake.id]
    # the handoff is audited (closes the spec 08 §5 ASSIGNED verb)
    acts = ledger.activity.by_subject("task", uid("t1"))
    assert [a.verb for a in acts] == [ActivityVerb.ASSIGNED]
    assert acts[0].actor_employee_id == "mgr"


def test_assign_unknown_task_returns_none(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    assert assign_task(ledger, uid("ghost"), uid("e1")) is None


def test_assign_terminal_task_returns_none(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="done thing", status=TaskStatus.DONE))
    assert assign_task(ledger, uid("t1"), uid("e1")) is None
    assert ledger.wakes.queued(employee_id=uid("e1")) == []  # no wake for an unassignable task


# -- messaging ------------------------------------------------------------------------------------


def test_deliver_message_persists_and_wakes_recipient(ledger: Ledger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, uid("rep"))
    wake = deliver_message(
        ledger,
        Message(id=uid("m1"), from_employee_id="mgr", to_employee_id=uid("rep"), body="do X"),
    )

    assert wake.reason is WakeReason.MESSAGE
    assert wake.employee_id == uid("rep")
    assert [m.id for m in ledger.messages.inbox(uid("rep"))] == [uid("m1")]
    assert [w.id for w in ledger.wakes.queued(employee_id=uid("rep"))] == [wake.id]


def test_message_wakes_coalesce_per_recipient(ledger: Ledger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, uid("rep"))
    deliver_message(
        ledger, Message(id=uid("m1"), from_employee_id="mgr", to_employee_id=uid("rep"), body="a")
    )
    deliver_message(
        ledger, Message(id=uid("m2"), from_employee_id="mgr", to_employee_id=uid("rep"), body="b")
    )
    # both messages land in the inbox, but the recipient gets a single "check your mail" wake
    assert len(ledger.messages.inbox(uid("rep"))) == 2
    assert len(ledger.wakes.queued(employee_id=uid("rep"))) == 1
