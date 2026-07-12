"""The chorus ``get_run`` capability — full prose drill-down for one past beat (R8)."""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicRecallService
from chorus_tools._recall_render import format_full_run


class GetRunInput(BaseModel):
    """Fetch one past beat in full — use after a teaser or recall slim hit."""

    run_id: str = Field(description="The episodic run_id from a teaser line or recall hit.")


class GetRunTool(BaseTool):
    """Full prose and metadata for one of your own past beats."""

    name = "get_run"
    description = (
        "Return the FULL account of one past beat by run_id — intent, outcome, files, "
        "artifacts, and complete narrative prose. Use after recall() or the beat-start teaser "
        "when you need what you actually tried. Read-only; your own beats only."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = GetRunInput

    def __init__(self, service: EpisodicRecallService) -> None:
        self._service = service

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = GetRunInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(content=f"refused: malformed get_run input — {exc}", is_error=True)

        beat = BeatContext.read(ctx.working_dir)
        delta = self._service.get_run(beat.employee_id, args.run_id)
        if delta is None:
            return ToolResult(
                content=f"refused: no beat {args.run_id!r} for this employee.",
                is_error=True,
            )
        body = format_full_run(delta)
        return ToolResult(
            content=body,
            structured={
                "status": "success",
                "run_id": delta.run_id,
                "outcome": delta.outcome,
                "task_id": delta.task_id,
            },
        )


__all__ = ["GetRunInput", "GetRunTool"]
