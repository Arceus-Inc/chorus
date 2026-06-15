"""MessageRepo — the durable mailbox (spec 01 Cluster G ``message``, spec 03 §2).

A message does not run anything — it lands here and (in the scheduler) enqueues a
``wake(reason='message')`` for the recipient. Sender is an employee XOR a human (DB CHECK). The
inbox is a recipient's unread messages, oldest first.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger import Message, MessageKind, SqliteLedger, Task
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: SqliteLedger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def test_send_and_get(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    sent = ledger.messages.send(
        Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="do X")
    )
    got = ledger.messages.get(sent.id)
    assert got is not None
    assert got.to_employee_id == "rep"
    assert got.from_employee_id == "mgr"
    assert got.body == "do X"
    assert got.kind is MessageKind.INSTRUCTION
    assert got.read_at is None


def test_inbox_returns_unread_for_recipient(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    _emp(ledger, "other")
    ledger.messages.send(Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="a"))
    ledger.messages.send(Message(id="m2", from_employee_id="mgr", to_employee_id="rep", body="b"))
    ledger.messages.send(Message(id="m3", from_employee_id="mgr", to_employee_id="other", body="c"))
    assert [m.id for m in ledger.messages.inbox("rep")] == ["m1", "m2"]


def test_mark_read_removes_from_inbox(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    ledger.messages.send(Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="a"))
    ledger.messages.mark_read("m1")
    assert ledger.messages.inbox("rep") == []
    got = ledger.messages.get("m1")
    assert got is not None
    assert got.read_at is not None


def test_human_sender_allowed(ledger: SqliteLedger) -> None:
    _emp(ledger, "rep")
    sent = ledger.messages.send(
        Message(id="m1", from_user_id="u1", to_employee_id="rep", body="hi", kind=MessageKind.FYI)
    )
    assert sent.from_user_id == "u1"
    assert sent.from_employee_id is None


def test_single_sender_xor_enforced(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    with pytest.raises(sqlite3.IntegrityError):
        ledger.messages.send(
            Message(
                id="m1",
                from_employee_id="mgr",
                from_user_id="u1",  # both senders set → CHECK violation
                to_employee_id="rep",
                body="x",
            )
        )


def test_message_can_anchor_to_task(ledger: SqliteLedger) -> None:
    _emp(ledger, "mgr")
    _emp(ledger, "rep")
    ledger.tasks.submit(Task(id="t1", intent="x"))
    sent = ledger.messages.send(
        Message(id="m1", from_employee_id="mgr", to_employee_id="rep", body="re t1", task_id="t1")
    )
    assert sent.task_id == "t1"
