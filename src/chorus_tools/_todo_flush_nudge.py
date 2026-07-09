"""Wrap dream tools so an armed beat-budget nudge reaches the model on the next tool call."""

from __future__ import annotations

from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration, ToolEffects
from dream.tools._context import ToolExecutionContext
from dream.tools._registry import ToolRegistry
from pydantic import BaseModel

from chorus.heartbeat._todo_flush import (
    clear_todo_flush_nudge,
    format_todo_flush_banner,
    read_todo_flush_nudge,
)


class _PlaceholderInput(BaseModel):
    """Placeholder so the wrapper class passes BaseTool validation."""


class TodoFlushNudgeToolWrapper(BaseTool):
    """Delegate to an inner tool; append the TODO flush warning when a nudge is armed."""

    name = "_todo_flush_wrapped"
    description = ""
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=1.0)
    input_model: type[BaseModel] = _PlaceholderInput

    def __init__(self, inner: BaseTool) -> None:
        self._inner = inner
        self.name = inner.name
        self.description = inner.description
        self.declaration = inner.declaration
        self.input_model = inner.input_model

    def effects_for(self, input: dict[str, Any]) -> ToolEffects:
        return self._inner.effects_for(input)

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        result = await self._inner.execute(input, ctx)
        nudge = read_todo_flush_nudge(ctx.working_dir)
        if nudge is None:
            return result
        if self.name == "todo_write" and not result.is_error:
            clear_todo_flush_nudge(ctx.working_dir)
        banner = format_todo_flush_banner(remaining_s=nudge.remaining_s)
        metadata = dict(result.metadata)
        metadata["warning"] = True
        existing = metadata.get("next_actions")
        extra = ("Sync TODO.md via todo_write before beat budget expires.",)
        if isinstance(existing, list):
            metadata["next_actions"] = [*extra, *[str(x) for x in existing]]
        else:
            metadata["next_actions"] = list(extra)
        return ToolResult(
            content=f"{result.content}\n\n{banner}",
            is_error=result.is_error,
            metadata=metadata,
        )


def registry_with_todo_flush_nudge(registry: ToolRegistry) -> ToolRegistry:
    """Return a registry whose tools surface an armed TODO flush nudge on the next call."""
    if registry.get("todo_write") is None:
        return registry
    wrapped = ToolRegistry()
    for tool, source in registry.iter_with_source():
        wrapped.register(TodoFlushNudgeToolWrapper(tool), source=source)
    return wrapped


__all__ = ["TodoFlushNudgeToolWrapper", "registry_with_todo_flush_nudge"]
