"""Typed helpers for chorus adapters consuming dream's ``RunTaskEvent`` stream."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Literal

from dream.runner.events import RoleText, RoleToolResult, RoleToolStart, RunTaskEvent

SPAWN_SUBAGENT_TOOL = "spawn_subagent"
MEMORY_TOOLS = frozenset({"recall", "lattice_context"})
_CONTENT_PREVIEW_LIMIT = 240


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
    "SpawnSubagentInput",
    "tool_result_content_preview",
]
