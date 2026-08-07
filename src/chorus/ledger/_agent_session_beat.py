"""Beat ↔ agent_session bridge — ledger is the sole conversation / tool-call SoT."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from chorus.ids import mint_id
from chorus.ledger._agent_session_store import (
    append_transcript,
    ensure_open_session,
    load_transcript,
)
from chorus.ledger._ledger import Ledger
from chorus.ledger._models import (
    AgentSession,
    ConversationMessage,
    ConversationRole,
    SessionCost,
    ToolCall,
)

_RESUME_HEADER: Final[str] = (
    "Prior session transcript (ledger source of truth — continue; do not re-ask):"
)
_MAX_RESUME_CHARS: Final[int] = 24_000
_MAX_TOOL_RESULT_CHARS: Final[int] = 2_000


def dream_session_key_for_task(task_id: str) -> str:
    """Stable dream key for a chorus task (one open thread per task)."""
    return f"task:{task_id}"


def begin_beat_session(
    ledger: Ledger,
    *,
    employee_id: str,
    task_id: str,
    run_id: str,
    model: str = "",
    system_prompt: str | None = None,
) -> AgentSession:
    """Open or resume the task's agent session and attach this beat's ``run_id``."""
    session = ensure_open_session(
        ledger,
        employee_id=employee_id,
        task_id=task_id,
        dream_session_key=dream_session_key_for_task(task_id),
        model=model,
        system_prompt=system_prompt,
        run_id=run_id,
    )
    if session.run_id != run_id:
        ledger.agent_sessions.touch_cost(session.id, session.cost, run_id=run_id)
        refreshed = ledger.agent_sessions.get(session.id)
        return refreshed if refreshed is not None else session
    return session


def resume_intent(ledger: Ledger, session_id: str, intent: str) -> str:
    """Prepend ledger transcript into the beat intent when prior history exists."""
    messages = list(load_transcript(ledger, session_id))
    # The current beat intent is already the prompt — drop a trailing user turn that
    # duplicates it (CLI chat records the operator line before the beat starts).
    intent_text = intent.strip()
    while (
        messages
        and messages[-1].role is ConversationRole.USER
        and _blocks_text(messages[-1].content).strip() == intent_text
    ):
        messages.pop()
    context = format_resume_context(
        messages,
        ledger.agent_sessions.tool_calls_for(session_id),
    )
    if not context:
        return intent
    return intent + "\n\n" + context


def format_resume_context(
    messages: Sequence[ConversationMessage],
    tool_calls: Sequence[ToolCall],
) -> str:
    """Render a compact resume block from durable rows (empty if nothing to resume)."""
    if not messages and not tool_calls:
        return ""
    lines: list[str] = [_RESUME_HEADER]
    for message in messages:
        text = _blocks_text(message.content)
        if text:
            lines.append(f"{message.role.value}: {text}")
    for call in tool_calls:
        result = (call.result_content or "").strip()
        if len(result) > _MAX_TOOL_RESULT_CHARS:
            result = result[:_MAX_TOOL_RESULT_CHARS] + "…"
        status = "error" if call.is_error else "ok"
        lines.append(f"tool {call.tool_name} ({status}): {result or '(no result yet)'}")
    body = "\n".join(lines)
    if len(body) <= _MAX_RESUME_CHARS:
        return body
    return body[-_MAX_RESUME_CHARS:]


def append_user_turn(ledger: Ledger, session_id: str, text: str) -> ConversationMessage:
    """Append one operator/user line to the durable transcript."""
    seq = ledger.agent_sessions.last_message_seq(session_id) + 1
    message = ConversationMessage(
        id=mint_id(),
        session_id=session_id,
        seq=seq,
        role=ConversationRole.USER,
        content=({"type": "text", "text": text},),
    )
    append_transcript(ledger, session_id, (message,))
    return message


@dataclass(frozen=True)
class BeatSessionDelta:
    """Parsed beat account ready to persist."""

    messages: tuple[ConversationMessage, ...]
    tool_starts: tuple[ToolCall, ...]
    tool_completions: tuple[tuple[str, str, bool], ...]  # tool_use_id, result, is_error


def parse_raw_record(
    raw_record: str,
    *,
    session_id: str,
    start_seq: int,
) -> BeatSessionDelta:
    """Map a beat ``raw_record`` JSONL stream into ledger rows (append-only shapes)."""
    messages: list[ConversationMessage] = []
    tool_starts: list[ToolCall] = []
    tool_completions: list[tuple[str, str, bool]] = []
    seq = start_seq
    pending_tool_ids: list[str] = []

    for line_no, line in enumerate(raw_record.splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        kind = str(event.get("kind", ""))
        if kind == "role.text":
            text = str(event.get("text", "")).strip()
            if not text:
                continue
            seq += 1
            messages.append(
                ConversationMessage(
                    id=mint_id(),
                    session_id=session_id,
                    seq=seq,
                    role=ConversationRole.ASSISTANT,
                    content=({"type": "text", "text": text},),
                )
            )
        elif kind == "role.tool.start":
            tool_name = str(event.get("tool") or event.get("name") or "tool")
            tool_use_id = str(event.get("tool_use_id") or event.get("id") or "")
            if not tool_use_id:
                tool_use_id = f"beat-tool-{line_no}"
            pending_tool_ids.append(tool_use_id)
            raw_input = event.get("input")
            tool_input: dict[str, object] = (
                {str(k): v for k, v in raw_input.items()}
                if isinstance(raw_input, Mapping)
                else {}
            )
            tool_starts.append(
                ToolCall(
                    id=mint_id(),
                    session_id=session_id,
                    tool_use_id=tool_use_id,
                    tool_name=tool_name,
                    input=tool_input,
                )
            )
        elif kind == "role.tool.result":
            tool_use_id = str(event.get("tool_use_id") or event.get("id") or "")
            if not tool_use_id and pending_tool_ids:
                tool_use_id = pending_tool_ids.pop(0)
            elif tool_use_id and pending_tool_ids and pending_tool_ids[0] == tool_use_id:
                pending_tool_ids.pop(0)
            elif not tool_use_id:
                tool_use_id = f"beat-tool-result-{line_no}"
            content = event.get("content")
            if content is None:
                content = event.get("content_preview", "")
            tool_completions.append(
                (tool_use_id, str(content), bool(event.get("is_error", False)))
            )

    return BeatSessionDelta(
        messages=tuple(messages),
        tool_starts=tuple(tool_starts),
        tool_completions=tuple(tool_completions),
    )


def persist_beat_account(
    ledger: Ledger,
    session_id: str,
    *,
    raw_record: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_cents: int = 0,
    run_id: str | None = None,
    seal: bool = False,
) -> BeatSessionDelta:
    """Append this beat's transcript + tool calls into the ledger (SoT write)."""
    del model  # reserved for a future model-update path on AgentSession
    start_seq = ledger.agent_sessions.last_message_seq(session_id)
    delta = parse_raw_record(raw_record, session_id=session_id, start_seq=start_seq)
    if delta.messages:
        append_transcript(ledger, session_id, delta.messages)
    existing = {row.tool_use_id for row in ledger.agent_sessions.tool_calls_for(session_id)}
    for call in delta.tool_starts:
        if call.tool_use_id not in existing:
            ledger.agent_sessions.record_tool_call(call)
            existing.add(call.tool_use_id)
    for tool_use_id, result_content, is_error in delta.tool_completions:
        ledger.agent_sessions.complete_tool_call(
            session_id,
            tool_use_id,
            result_content=result_content,
            is_error=is_error,
        )
    session = ledger.agent_sessions.get(session_id)
    prior = session.cost if session is not None else SessionCost()
    cost = SessionCost(
        input_tokens=prior.input_tokens + max(0, input_tokens),
        output_tokens=prior.output_tokens + max(0, output_tokens),
        cache_read_tokens=prior.cache_read_tokens,
        cache_write_tokens=prior.cache_write_tokens,
        cost_usd=prior.cost_usd + (max(0, cost_cents) / 100.0),
    )
    ledger.agent_sessions.touch_cost(session_id, cost, run_id=run_id)
    if seal:
        ledger.agent_sessions.seal(session_id)
    return delta


def _blocks_text(content: Sequence[Mapping[str, object]]) -> str:
    parts: list[str] = []
    for block in content:
        text = block.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


__all__ = [
    "BeatSessionDelta",
    "append_user_turn",
    "begin_beat_session",
    "dream_session_key_for_task",
    "format_resume_context",
    "parse_raw_record",
    "persist_beat_account",
    "resume_intent",
]
