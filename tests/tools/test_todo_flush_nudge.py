"""Todo flush nudge tool wrapper — surfaces beat-budget warning on the next tool call."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus.heartbeat._todo_flush import read_todo_flush_nudge, write_todo_flush_nudge
from chorus.testing import uid
from chorus_tools._todo_flush_nudge import TodoFlushNudgeToolWrapper

pytestmark = pytest.mark.unit


class _EchoInput(BaseModel):
    text: str = Field(default="")


class _EchoTool(BaseTool):
    name = "echo"
    description = "echo"
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=1.0)
    input_model = _EchoInput

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        del ctx
        return ToolResult(content=f"echo:{input.get('text', '')}", metadata={"summary": "ok"})


class _TodoWriteInput(BaseModel):
    item: str


class _TodoWriteStub(BaseTool):
    name = "todo_write"
    description = "todo"
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=1.0)
    input_model = _TodoWriteInput

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        del ctx
        return ToolResult(content=f"wrote {input['item']}", metadata={"changed": True})


def _ctx(tmp_path: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=tmp_path, session_id=uid("s1"))


async def test_wrapper_passthrough_without_nudge(tmp_path: Path) -> None:
    tool = TodoFlushNudgeToolWrapper(_EchoTool())
    result = await tool.execute({"text": "hi"}, _ctx(tmp_path))
    assert result.content == "echo:hi"
    assert "BEAT BUDGET" not in result.content


async def test_wrapper_appends_banner_when_nudge_armed(tmp_path: Path) -> None:
    write_todo_flush_nudge(tmp_path, timeout_s=100.0, remaining_s=10.0)
    tool = TodoFlushNudgeToolWrapper(_EchoTool())
    result = await tool.execute({"text": "hi"}, _ctx(tmp_path))
    assert "echo:hi" in result.content
    assert "BEAT BUDGET WARNING" in result.content
    assert result.metadata.get("warning") is True
    assert read_todo_flush_nudge(tmp_path) is not None


async def test_wrapper_clears_nudge_after_todo_write(tmp_path: Path) -> None:
    write_todo_flush_nudge(tmp_path, timeout_s=100.0, remaining_s=10.0)
    tool = TodoFlushNudgeToolWrapper(_TodoWriteStub())
    await tool.execute({"item": "ship tests"}, _ctx(tmp_path))
    assert read_todo_flush_nudge(tmp_path) is None
