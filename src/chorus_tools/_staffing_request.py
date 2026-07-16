"""Model-callable staffing-gap request for an active delegation lead."""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.governance import StaffingRequestService
from chorus.heartbeat import BeatContext
from chorus.ledger import SqliteLedger, StaffingNeed


class StaffingNeedInput(BaseModel):
    profession: str
    count: int = Field(default=1, ge=1)


class StaffingRequestInput(BaseModel):
    rationale: str
    needs: list[StaffingNeedInput] = Field(min_length=1)


class StaffingRequestTool(BaseTool):
    """Open a governed staffing request without hiring or changing authority."""

    name = "staffing_request"
    description = (
        "Request missing direct-report professions for the current delegated objective after "
        "team_read shows no legal candidates. This records a staffing gap only; it does not hire, "
        "change authority, add Team members, or decompose work."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = StaffingRequestInput

    def __init__(self, ledger: SqliteLedger) -> None:
        self._service = StaffingRequestService(ledger)

    async def execute(
        self, input: dict[str, object], ctx: ToolExecutionContext
    ) -> ToolResult:
        try:
            args = StaffingRequestInput.model_validate(input)
            beat = BeatContext.read(ctx.working_dir)
            request = self._service.request(
                task_id=beat.task_id,
                requested_by_employee_id=beat.employee_id,
                rationale=args.rationale,
                needs=tuple(
                    StaffingNeed(need.profession, need.count) for need in args.needs
                ),
            )
        except (ValidationError, ValueError) as exc:
            return ToolResult(
                content=f"refused: invalid staffing request — {exc}",
                structured={"error": str(exc)},
                is_error=True,
            )
        return ToolResult(
            content=(
                f"opened staffing request {request.id}; no employees, authority, or Team "
                "memberships were changed"
            ),
            structured={
                "staffing_request_id": request.id,
                "status": request.status.value,
                "goal_id": request.goal_id,
                "team_id": request.team_id,
                "requires_ceo_plan": True,
                "requires_human_approval": True,
            },
        )


__all__ = ["StaffingNeedInput", "StaffingRequestInput", "StaffingRequestTool"]