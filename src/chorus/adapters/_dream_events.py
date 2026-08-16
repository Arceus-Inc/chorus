"""Typed helpers for chorus adapters consuming dream's ``RunTaskEvent`` stream.

Dream #107 exports ``RoleSessionRecovered`` on ``dream.runner.events`` and adds
it to ``RunTaskEvent``. Chorus never decodes dict observer payloads. A local
compatibility dataclass remains only until the installed dream pin includes that
export; then delete the copy, drop the fallback, and type observers as
``RunTaskEvent`` only.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal, Protocol, runtime_checkable

from dream.runner import events as dream_events
from dream.runner.events import RoleText, RoleToolResult, RoleToolStart, RunTaskEvent

from chorus.heartbeat._beat import (
    SessionRecoveryAction,
    SessionRecoveryNotice,
    SessionRecoveryReason,
)

SPAWN_SUBAGENT_TOOL = "spawn_subagent"
MEMORY_TOOLS = frozenset({"recall", "lattice_context"})
_CONTENT_PREVIEW_LIMIT = 240

# Dream #107 (merged) exports this dataclass; older pins omit the name.
_dream_recovered_attr: object = getattr(dream_events, "RoleSessionRecovered", None)
_DREAM_ROLE_SESSION_RECOVERED: type[object] | None = (
    _dream_recovered_attr if isinstance(_dream_recovered_attr, type) else None
)


@runtime_checkable
class _RoleSessionRecoveredView(Protocol):
    """Structural view of Dream #107's typed ``role.session.recovered`` event."""

    role: str
    session_id: str
    requested_session_id: str
    reason: str
    action: str
    snapshot_preserved: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class RoleSessionRecovered:
    """Typed ``role.session.recovered`` envelope matching Dream #107's export.

    ``session_id`` is the active recovered session; ``requested_session_id`` is the
    handle Dream failed to resume. Do not accept dict events here.
    """

    role: str
    session_id: str
    requested_session_id: str
    reason: str
    action: str
    snapshot_preserved: bool


def session_recovery_notice_from_dream_event(event: object) -> SessionRecoveryNotice | None:
    """Decode a typed recovery event without letting malformed observer data affect a beat.

    Dict payloads are rejected. Only :class:`RoleSessionRecovered` (or Dream's export
    of that same dataclass) is accepted.
    """
    recovered = _as_role_session_recovered(event)
    if recovered is None:
        return None
    if not (
        recovered.role
        and recovered.session_id
        and recovered.requested_session_id
        and type(recovered.snapshot_preserved) is bool
    ):
        return None
    try:
        return SessionRecoveryNotice(
            role=recovered.role,
            session_id=recovered.session_id,
            requested_session_id=recovered.requested_session_id,
            reason=SessionRecoveryReason(_recovery_token(recovered.reason)),
            action=SessionRecoveryAction(_recovery_token(recovered.action)),
            snapshot_preserved=recovered.snapshot_preserved,
        )
    except ValueError:
        return None


def _recovery_token(value: object) -> str:
    """Normalize Dream's Literal/enum recovery fields to the Chorus closed vocabulary."""
    if isinstance(value, str):
        return value
    raw = getattr(value, "value", None)
    return raw if isinstance(raw, str) else ""


def _as_role_session_recovered(event: object) -> RoleSessionRecovered | None:
    """Accept Chorus's contract type or Dream's export of the same dataclass."""
    if isinstance(event, Mapping):
        return None
    if isinstance(event, RoleSessionRecovered):
        return event
    if (
        _DREAM_ROLE_SESSION_RECOVERED is not None
        and isinstance(event, _DREAM_ROLE_SESSION_RECOVERED)
        and isinstance(event, _RoleSessionRecoveredView)
    ):
        return RoleSessionRecovered(
            role=event.role,
            session_id=event.session_id,
            requested_session_id=event.requested_session_id,
            reason=event.reason,
            action=event.action,
            snapshot_preserved=event.snapshot_preserved,
        )
    return None


@dataclass(frozen=True, slots=True)
class SpawnSubagentInput:
    """Parsed ``spawn_subagent`` tool arguments."""

    name: str
    prompt: str

    @classmethod
    def parse(cls, tool_input: Mapping[str, object]) -> SpawnSubagentInput:
        name = str(tool_input.get("subagent_type") or tool_input.get("name") or "subagent")
        return cls(name=name, prompt=str(tool_input.get("prompt", "")))


@dataclass(frozen=True, slots=True)
class MemoryHit:
    run_id: str


@dataclass(frozen=True, slots=True)
class MemoryRetrieval:
    """Structured recall / lattice_context outcome lifted to a chorus memory event."""

    tool: str
    hits: tuple[MemoryHit, ...]
    is_error: bool

    @property
    def empty(self) -> bool:
        return not self.hits

    @classmethod
    def from_tool_result(cls, event: RoleToolResult) -> MemoryRetrieval | None:
        if event.tool not in MEMORY_TOOLS:
            return None
        hits: tuple[MemoryHit, ...] = ()
        if event.structured is not None:
            hits_raw = event.structured.get("hits")
            if isinstance(hits_raw, list):
                hits = tuple(
                    MemoryHit(run_id=str(item["run_id"]))
                    for item in hits_raw
                    if isinstance(item, Mapping) and "run_id" in item
                )
        return cls(tool=event.tool, hits=hits, is_error=event.is_error)


@dataclass(frozen=True, slots=True)
class ReasoningRecordLine:
    """One episodic raw-record line — a slim, JSON-serializable view of a role event."""

    kind: Literal["role.text", "role.tool.start", "role.tool.result"]
    role: str
    text: str | None = None
    tool: str | None = None
    input: Mapping[str, object] | None = None
    is_error: bool | None = None
    content: str | None = None

    @classmethod
    def from_event(cls, event: RunTaskEvent) -> ReasoningRecordLine | None:
        if isinstance(event, RoleText):
            return cls(kind="role.text", role=event.role, text=event.text)
        if isinstance(event, RoleToolStart):
            return cls(
                kind="role.tool.start",
                role=event.role,
                tool=event.tool,
                input=event.input,
            )
        if isinstance(event, RoleToolResult):
            return cls(
                kind="role.tool.result",
                role=event.role,
                tool=event.tool,
                is_error=event.is_error,
                content=event.content,
            )
        return None

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str, ensure_ascii=False)


def tool_result_content_preview(content: str) -> str:
    """Bounded preview for consumers that still read ``content_preview``."""
    if len(content) <= _CONTENT_PREVIEW_LIMIT:
        return content
    return content[:_CONTENT_PREVIEW_LIMIT]


__all__ = [
    "MEMORY_TOOLS",
    "SPAWN_SUBAGENT_TOOL",
    "MemoryHit",
    "MemoryRetrieval",
    "ReasoningRecordLine",
    "RoleSessionRecovered",
    "SpawnSubagentInput",
    "session_recovery_notice_from_dream_event",
    "tool_result_content_preview",
]
