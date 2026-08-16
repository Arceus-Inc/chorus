"""High-level helpers over the agent-session handle rows."""

from __future__ import annotations

from chorus.ids import mint_id
from chorus.ledger._ledger import Ledger
from chorus.ledger._models import AgentSession


def dream_session_key_for_handle(session_id: str) -> str:
    """Provider scope owned by one provider-neutral Chorus session handle."""
    return f"session-{session_id}"


def ensure_open_session(
    ledger: Ledger,
    *,
    employee_id: str,
    task_id: str,
    dream_session_key: str | None = None,
    model: str,
    run_id: str | None,
    working_dir: str | None = None,
) -> AgentSession:
    """Resume the open session for a task, or open a new one."""
    existing = ledger.agent_sessions.get_open_for_task(task_id)
    if existing is not None:
        return existing
    session_id = mint_id()
    session = AgentSession(
        id=session_id,
        dream_session_key=(
            dream_session_key
            if dream_session_key is not None
            else dream_session_key_for_handle(session_id)
        ),
        employee_id=employee_id,
        task_id=task_id,
        run_id=run_id,
        model=model,
        working_dir=working_dir,
    )
    return ledger.agent_sessions.open(session)


__all__ = ["dream_session_key_for_handle", "ensure_open_session"]
