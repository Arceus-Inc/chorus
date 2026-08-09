"""Beat ↔ agent_session bridge — chorus holds the key, dream holds the conversation.

A beat opens (or reopens) the task's handle row, hands dream the session key so
``run_task`` continues the same planner / generator / evaluator threads, and
meters what the beat spent back onto the row. The transcript itself never comes
through here: dream reloads it from its own store, which is the difference
between resuming a conversation and replaying a summary of one into a prompt.
"""

from __future__ import annotations

from chorus.ledger._agent_session_store import ensure_open_session
from chorus.ledger._ledger import Ledger
from chorus.ledger._models import AgentSession, AgentSessionStatus, SessionCost


def dream_session_key_for_task(task_id: str) -> str:
    """Stable dream scope for a chorus task (one thread per role beneath it).

    Hyphen-separated because dream turns the scope into a directory name under
    its sidecar root and rejects ``:`` there.
    """
    return f"task-{task_id}"


def begin_beat_session(
    ledger: Ledger,
    *,
    employee_id: str,
    task_id: str,
    run_id: str,
    model: str = "",
    working_dir: str | None = None,
) -> AgentSession:
    """Open or resume the task's agent session and attach this beat's ``run_id``."""
    session = ensure_open_session(
        ledger,
        employee_id=employee_id,
        task_id=task_id,
        model=model,
        run_id=run_id,
        working_dir=working_dir,
    )
    if working_dir is not None and session.working_dir is None:
        ledger.agent_sessions.bind_working_dir(session.id, working_dir)
        session = ledger.agent_sessions.get(session.id) or session
    if session.run_id != run_id:
        ledger.agent_sessions.touch_cost(session.id, session.cost, run_id=run_id)
        refreshed = ledger.agent_sessions.get(session.id)
        return refreshed if refreshed is not None else session
    return session


def persist_beat_account(
    ledger: Ledger,
    session_id: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_cents: int = 0,
    run_id: str | None = None,
    last_error: str | None = None,
    seal: bool = False,
) -> SessionCost:
    """Meter this beat's spend onto the handle row and return the running total."""
    session = ledger.agent_sessions.get(session_id)
    prior = session.cost if session is not None else SessionCost()
    cost = SessionCost(
        input_tokens=prior.input_tokens + max(0, input_tokens),
        output_tokens=prior.output_tokens + max(0, output_tokens),
        cache_read_tokens=prior.cache_read_tokens,
        cache_write_tokens=prior.cache_write_tokens,
        cost_usd=prior.cost_usd + (max(0, cost_cents) / 100.0),
    )
    if session is None or session.status is not AgentSessionStatus.OPEN:
        return prior
    accounted = ledger.agent_sessions.account_if_open(
        session_id,
        cost,
        run_id=run_id,
        last_error=last_error,
        seal=seal,
    )
    return cost if accounted else prior


__all__ = [
    "begin_beat_session",
    "dream_session_key_for_task",
    "persist_beat_account",
]
