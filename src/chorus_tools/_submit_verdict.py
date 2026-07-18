"""The Reviewer's verdict tool for review beats (M3 — the load-bearing Reviewer).

A reviewer beat inspects the work under review (read-only, in the worker's worktree) and calls this once
to record its approve/block decision. The verdict IS the work task's ``agent_review`` DoD verdict; the
kernel reads it back after the beat and lands the work (approve) or routes the block.
"""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger
from chorus.lifecycle import CapabilityService


class SubmitVerdictInput(BaseModel):
    """Arguments for ``submit_verdict`` — the reviewer's decision on the work under review."""

    approve: bool = Field(
        description="true to approve the work as meeting the rubric, false to block it for changes"
    )
    feedback: str = Field(
        description="concrete reasons for the verdict; when blocking, say exactly what must change"
    )
    verify_command: str = Field(
        default="",
        description=(
            "for a code task: the project's verify command to run (e.g. 'npm ci && npm test', "
            "'cargo test', 'pytest -q'), discovered from the project's files. The kernel runs it as the "
            "objective gate. Leave empty for a non-code review."
        ),
    )


class SubmitVerdictTool(BaseTool):
    """Record the reviewer's approve/block verdict on the task under review."""

    name = "submit_verdict"
    description = (
        "Render your verdict on the work under review. Call exactly once: approve=true if it meets the "
        "rubric, approve=false to block it. Always give concrete feedback; when blocking, state exactly "
        "what must change so the work can be fixed."
    )
    # risk="safe" + tier_required=0: ``risk`` is dream's *sandbox* axis (repo/system mutation). The
    # verdict touches no files / commands / network — it writes only the ledger — so from the sandbox's
    # view it is safe, exactly like dream's working-memory journaling (also risk="safe", tier 0, and
    # explicitly allowed under a read-only repo tier). A read-only Reviewer must always be able to record
    # its verdict; classifying it "mutating" makes the read-only sandbox *deny the call at execution*
    # (the model emits the tool call, dream refuses it), which silently strands the review.
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = SubmitVerdictInput

    def __init__(self, ledger: Ledger) -> None:
        self._service = CapabilityService(ledger)

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        args = SubmitVerdictInput.model_validate(input)
        beat = BeatContext.read(ctx.working_dir)
        result = self._service.record_verdict(
            task_id=beat.task_id,
            run_id=beat.run_id,
            reviewer_id=beat.employee_id,
            approve=args.approve,
            feedback=args.feedback,
            verify_command=args.verify_command,
        )
        if result.not_reviewable:
            return ToolResult(
                content="refused: this task has no agent-review DoD to render a verdict on",
                structured={"not_reviewable": True},
                is_error=True,
            )
        if result.self_review:
            return ToolResult(
                content="refused: you cannot render a verdict on your own work",
                structured={"self_review": True},
                is_error=True,
            )
        decision = "approved" if result.approved else "blocked"
        return ToolResult(
            content=f"verdict recorded: {decision}",
            structured={"approved": result.approved},
        )


__all__ = ["SubmitVerdictInput", "SubmitVerdictTool"]
