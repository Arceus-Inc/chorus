"""AgentSessionRepo — durable dream conversation + tool-call history (migration 0005)."""

from __future__ import annotations

import pytest

from chorus.ledger import (
    AgentSession,
    AgentSessionStatus,
    ConversationMessage,
    ConversationRole,
    Ledger,
    LedgerIntegrityError,
    Run,
    SessionCost,
    Task,
    ToolCall,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _employee(ledger: Ledger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def _task(ledger: Ledger, task_id: str, *, assignee: str | None = None) -> str:
    ledger.tasks.submit(
        Task(id=task_id, intent="agent session test", assignee_employee_id=assignee)
    )
    return task_id


def _session(
    ledger: Ledger,
    *,
    session_id: str | None = None,
    dream_key: str | None = None,
    employee_id: str,
    task_id: str,
) -> AgentSession:
    return AgentSession(
        id=session_id or uid("sess"),
        dream_session_key=dream_key or uid("dream"),
        employee_id=employee_id,
        task_id=task_id,
        model="claude-sonnet",
        system_prompt="You are helpful.",
    )


def test_open_get_and_get_open_for_task(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    opened = ledger.agent_sessions.open(session)
    assert opened.id == uid("s1")
    assert opened.status is AgentSessionStatus.OPEN
    got = ledger.agent_sessions.get(uid("s1"))
    assert got is not None
    assert got.dream_session_key == session.dream_session_key
    assert got.employee_id == emp
    assert got.task_id == task_id
    assert ledger.agent_sessions.get_open_for_task(task_id) == got


def test_second_open_for_same_task_raises(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.agent_sessions.open(_session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1")))
    with pytest.raises(LedgerIntegrityError):
        ledger.agent_sessions.open(
            _session(
                ledger,
                employee_id=emp,
                task_id=task_id,
                session_id=uid("s2"),
                dream_key=uid("dream2"),
            )
        )


def test_append_messages_and_all_messages_preserve_order(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    messages = [
        ConversationMessage(
            id=uid("m1"),
            session_id=session.id,
            seq=1,
            role=ConversationRole.USER,
            content=({"type": "text", "text": "hello"},),
        ),
        ConversationMessage(
            id=uid("m2"),
            session_id=session.id,
            seq=2,
            role=ConversationRole.ASSISTANT,
            content=({"type": "text", "text": "hi there"},),
        ),
    ]
    ledger.agent_sessions.append_messages(messages)
    loaded = ledger.agent_sessions.all_messages(session.id)
    assert [m.id for m in loaded] == [uid("m1"), uid("m2")]
    assert [m.seq for m in loaded] == [1, 2]
    assert loaded[0].role is ConversationRole.USER
    assert loaded[1].content[0]["text"] == "hi there"


def test_messages_after_cursor_pagination(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    ledger.agent_sessions.append_messages(
        [
            ConversationMessage(
                id=uid(f"m{i}"),
                session_id=session.id,
                seq=i,
                role=ConversationRole.USER if i % 2 else ConversationRole.ASSISTANT,
                content=({"type": "text", "text": f"msg-{i}"},),
            )
            for i in range(1, 6)
        ]
    )
    page1 = ledger.agent_sessions.messages_after(session.id, after_seq=0, limit=2)
    assert [m.seq for m in page1] == [1, 2]
    page2 = ledger.agent_sessions.messages_after(session.id, after_seq=2, limit=2)
    assert [m.seq for m in page2] == [3, 4]
    page3 = ledger.agent_sessions.messages_after(session.id, after_seq=4, limit=10)
    assert [m.seq for m in page3] == [5]


def test_record_complete_tool_calls(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    call = ToolCall(
        id=uid("tc1"),
        session_id=session.id,
        tool_use_id=uid("use1"),
        tool_name="grep",
        input={"pattern": "foo"},
    )
    recorded = ledger.agent_sessions.record_tool_call(call)
    assert recorded.tool_name == "grep"
    ledger.agent_sessions.complete_tool_call(
        session.id,
        uid("use1"),
        result_content="found 3 matches",
        is_error=False,
    )
    calls = ledger.agent_sessions.tool_calls_for(session.id)
    assert len(calls) == 1
    assert calls[0].result_content == "found 3 matches"
    assert calls[0].is_error is False
    assert calls[0].completed_at is not None


def test_seal_allows_new_open_for_same_task(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    first = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    ledger.agent_sessions.seal(first.id)
    sealed = ledger.agent_sessions.get(first.id)
    assert sealed is not None
    assert sealed.status is AgentSessionStatus.SEALED
    assert ledger.agent_sessions.get_open_for_task(task_id) is None
    second = ledger.agent_sessions.open(
        _session(
            ledger,
            employee_id=emp,
            task_id=task_id,
            session_id=uid("s2"),
            dream_key=uid("dream2"),
        )
    )
    assert second.id == uid("s2")
    assert ledger.agent_sessions.get_open_for_task(task_id) == second


def test_touch_cost_updates_session(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    run_id = uid("run1")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.runs.create(Run(id=run_id, employee_id=emp, task_id=task_id))
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    cost = SessionCost(input_tokens=100, output_tokens=50, cost_usd=0.01)
    ledger.agent_sessions.touch_cost(session.id, cost, run_id=run_id)
    got = ledger.agent_sessions.get(session.id)
    assert got is not None
    assert got.cost.input_tokens == 100
    assert got.cost.output_tokens == 50
    assert got.cost.cost_usd == 0.01
    assert got.run_id == run_id


def test_get_by_dream_key(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    dream_key = uid("dream")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.agent_sessions.open(
        _session(
            ledger,
            employee_id=emp,
            task_id=task_id,
            session_id=uid("s1"),
            dream_key=dream_key,
        )
    )
    got = ledger.agent_sessions.get_by_dream_key(dream_key)
    assert got is not None
    assert got.id == uid("s1")


def test_abort_session(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    ledger.agent_sessions.abort(session.id)
    got = ledger.agent_sessions.get(session.id)
    assert got is not None
    assert got.status is AgentSessionStatus.ABORTED
    assert ledger.agent_sessions.get_open_for_task(task_id) is None
