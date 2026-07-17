"""MessageRepo — the durable mailbox (spec 01 Cluster G ``message``, spec 03 §2).

A message does not run anything — it lands here and (in the scheduler) enqueues a
``wake(reason='message')`` for the recipient. Sender is an employee XOR a human (DB CHECK). The
inbox is a recipient's unread messages, oldest first.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger, LedgerIntegrityError, Message, MessageKind, Task
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def test_send_and_get(ledger: Ledger) -> None:
    _emp(ledger, uid("mgr"))
    _emp(ledger, uid("rep"))
    sent = ledger.messages.send(
        Message(id=uid("m1"), from_employee_id=uid("mgr"), to_employee_id=uid("rep"), body="do X")
    )
    got = ledger.messages.get(sent.id)
    assert got is not None
    assert got.to_employee_id == uid("rep")
    assert got.from_employee_id == uid("mgr")
    assert got.body == "do X"
    assert got.kind is MessageKind.INSTRUCTION
    assert got.read_at is None


def test_inbox_returns_unread_for_recipient(ledger: Ledger) -> None:
    _emp(ledger, uid("mgr"))
    _emp(ledger, uid("rep"))
    _emp(ledger, uid("other"))
    ledger.messages.send(
        Message(id=uid("m1"), from_employee_id=uid("mgr"), to_employee_id=uid("rep"), body="a")
    )
    ledger.messages.send(
        Message(id=uid("m2"), from_employee_id=uid("mgr"), to_employee_id=uid("rep"), body="b")
    )
    ledger.messages.send(
        Message(id=uid("m3"), from_employee_id=uid("mgr"), to_employee_id=uid("other"), body="c")
    )
    assert [m.id for m in ledger.messages.inbox(uid("rep"))] == [uid("m1"), uid("m2")]


def test_mark_read_removes_from_inbox(ledger: Ledger) -> None:
    _emp(ledger, uid("mgr"))
    _emp(ledger, uid("rep"))
    ledger.messages.send(
        Message(id=uid("m1"), from_employee_id=uid("mgr"), to_employee_id=uid("rep"), body="a")
    )
    ledger.messages.mark_read(uid("m1"))
    assert ledger.messages.inbox(uid("rep")) == []
    got = ledger.messages.get(uid("m1"))
    assert got is not None
    assert got.read_at is not None


def test_human_sender_allowed(ledger: Ledger) -> None:
    _emp(ledger, uid("rep"))
    sent = ledger.messages.send(
        Message(
            id=uid("m1"),
            from_user_id=uid("u1"),
            to_employee_id=uid("rep"),
            body="hi",
            kind=MessageKind.FYI,
        )
    )
    assert sent.from_user_id == uid("u1")
    assert sent.from_employee_id is None


def test_single_sender_xor_enforced(ledger: Ledger) -> None:
    _emp(ledger, uid("mgr"))
    _emp(ledger, uid("rep"))
    with pytest.raises(LedgerIntegrityError):
        ledger.messages.send(
            Message(
                id=uid("m1"),
                from_employee_id=uid("mgr"),
                from_user_id=uid("u1"),  # both senders set → CHECK violation
                to_employee_id=uid("rep"),
                body="x",
            )
        )


def test_message_can_anchor_to_task(ledger: Ledger) -> None:
    _emp(ledger, uid("mgr"))
    _emp(ledger, uid("rep"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    sent = ledger.messages.send(
        Message(
            id=uid("m1"),
            from_employee_id=uid("mgr"),
            to_employee_id=uid("rep"),
            body="re t1",
            task_id=uid("t1"),
        )
    )
    assert sent.task_id == uid("t1")
