"""Eval: agent session transcript survives a ledger reconnect (process restart simulation)."""

from __future__ import annotations

import uuid

import pytest

from chorus.ids import mint_id
from chorus.ledger import (
    ConversationMessage,
    ConversationRole,
    Ledger,
    Task,
    ToolCall,
    ensure_open_session,
    load_transcript,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def test_eval_agent_session_resume_after_reconnect(
    pg_database: str,
) -> None:
    """Multi-turn transcript + tool call reload identically after closing and reopening the ledger."""
    company_id = str(uuid.uuid4())
    emp = uid("emp")
    task_id = uid("task")
    dream_key = uid("dream")

    store = Ledger.open(pg_database, company_id=company_id)
    store.employees.create(Employee(id=emp, name=emp, role="engineer"))
    store.tasks.submit(Task(id=task_id, intent="resume eval", assignee_employee_id=emp))
    session = ensure_open_session(
        store,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_key,
        model="claude-sonnet",
        system_prompt="You are helpful.",
        run_id=None,
    )
    session_id = session.id
    store.agent_sessions.append_messages(
        [
            ConversationMessage(
                id=mint_id(),
                session_id=session_id,
                seq=1,
                role=ConversationRole.USER,
                content=({"type": "text", "text": "find the bug"},),
            ),
            ConversationMessage(
                id=mint_id(),
                session_id=session_id,
                seq=2,
                role=ConversationRole.ASSISTANT,
                content=({"type": "text", "text": "I'll search the codebase."},),
            ),
        ]
    )
    tool_use_id = uid("tool-use")
    store.agent_sessions.record_tool_call(
        ToolCall(
            id=mint_id(),
            session_id=session_id,
            tool_use_id=tool_use_id,
            tool_name="grep",
            input={"pattern": "bug"},
        )
    )
    store.agent_sessions.complete_tool_call(
        session_id,
        tool_use_id,
        result_content="src/foo.py:42",
        is_error=False,
    )
    store.close()

    resumed = Ledger.open(pg_database, company_id=company_id)
    try:
        open_session = resumed.agent_sessions.get_open_for_task(task_id)
        assert open_session is not None
        assert open_session.id == session_id
        assert open_session.dream_session_key == dream_key

        messages = load_transcript(resumed, session_id)
        assert len(messages) == 2
        assert messages[0].role is ConversationRole.USER
        assert messages[0].content[0]["text"] == "find the bug"
        assert messages[1].role is ConversationRole.ASSISTANT

        calls = resumed.agent_sessions.tool_calls_for(session_id)
        assert len(calls) == 1
        assert calls[0].tool_name == "grep"
        assert calls[0].result_content == "src/foo.py:42"
        assert calls[0].is_error is False
    finally:
        resumed.close()
