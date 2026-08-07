"""Agent session row models — durable dream conversation + tool-call history."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class AgentSessionStatus(StrEnum):
    OPEN = "open"
    SEALED = "sealed"
    ABORTED = "aborted"


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class SessionCost:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class AgentSession:
    id: str
    dream_session_key: str
    employee_id: str
    task_id: str
    run_id: str | None = None
    model: str = ""
    system_prompt: str | None = None
    status: AgentSessionStatus = AgentSessionStatus.OPEN
    cost: SessionCost = field(default_factory=SessionCost)
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class ConversationMessage:
    id: str
    session_id: str
    seq: int
    role: ConversationRole
    content: tuple[Mapping[str, object], ...]  # JSON content blocks
    created_at: datetime | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    session_id: str
    tool_use_id: str
    tool_name: str
    input: Mapping[str, object] = field(default_factory=dict)
    result_content: str | None = None
    is_error: bool | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None
