"""Agent session row model — chorus's pointer at a dream conversation.

dream is the runtime, so dream owns the transcript: messages and tool calls live
in its own session store, and a beat continues a thread by handing it back the
key. What chorus keeps is the control-plane row that maps ``(employee, task)``
to that key, alongside the things chorus is actually responsible for — spend
against a budget, which run touched the thread last, and why a resume failed.

Mirroring the messages here would give the same conversation two sources of
truth, and the one chorus held would be the stale copy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class AgentSessionStatus(StrEnum):
    OPEN = "open"
    SEALED = "sealed"
    ABORTED = "aborted"


@dataclass(frozen=True)
class SessionCost:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class AgentSession:
    """One task's thread with dream, as chorus records it.

    ``dream_session_key`` is the scope a beat passes to ``run_task``; dream
    derives a session per role beneath it. ``working_dir`` records where the
    thread did its work, so chorus can tell a mismatch from a missing session
    before it asks dream to resume. ``last_error`` carries the reason the last
    resume failed, which is what turns a poisoned thread into a decision
    instead of a silent restart.
    """

    id: str
    dream_session_key: str
    employee_id: str
    task_id: str
    run_id: str | None = None
    model: str = ""
    working_dir: str | None = None
    last_error: str | None = None
    status: AgentSessionStatus = AgentSessionStatus.OPEN
    cost: SessionCost = field(default_factory=SessionCost)
    created_at: datetime | None = None
    updated_at: datetime | None = None
