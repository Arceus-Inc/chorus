"""High-level helpers for durable agent session transcripts."""

from __future__ import annotations

from collections.abc import Sequence

from chorus.ids import mint_id
from chorus.ledger._ledger import Ledger
from chorus.ledger._models import AgentSession, ConversationMessage


def load_transcript(ledger: Ledger, session_id: str) -> list[ConversationMessage]:
    """Return the full ordered transcript for a session."""
    return ledger.agent_sessions.all_messages(session_id)


def ensure_open_session(
    ledger: Ledger,
    *,
    employee_id: str,
    task_id: str,
    dream_session_key: str,
    model: str,
    system_prompt: str | None,
    run_id: str | None,
) -> AgentSession:
    """Resume the open session for a task, or open a new one."""
    existing = ledger.agent_sessions.get_open_for_task(task_id)
    if existing is not None:
        return existing
    session = AgentSession(
        id=mint_id(),
        dream_session_key=dream_session_key,
        employee_id=employee_id,
        task_id=task_id,
        run_id=run_id,
        model=model,
        system_prompt=system_prompt,
    )
    return ledger.agent_sessions.open(session)


def append_transcript(
    ledger: Ledger,
    session_id: str,
    messages: Sequence[ConversationMessage],
) -> None:
    """Append-only transcript write — never replace in-memory style."""
    ledger.agent_sessions.append_messages(messages)
