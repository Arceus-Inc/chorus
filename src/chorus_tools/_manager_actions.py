"""Bounded manager action tools for integrate beats (M3 Slice 2)."""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.ledger import ExecutionMode, Ledger
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.lifecycle._file_scope import FileScopeViolation, describe_file_scope_violation


class SubmitTaskInput(BaseModel):
    """Arguments for ``submit_task`` — one follow-up child for the current parent task."""

    label: str = Field(
        description="a short stable name for this child task, unique under the parent"
    )
    intent: str = Field(description="what the follow-up task should accomplish")
    assignee: str = Field(description="the employee id of the direct report who will own this task")
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.DELIVERY,
        description="delivery for specialist work, delegation for a nested management assignment",
    )
    can_subdelegate: bool = Field(
        default=False,
        description="explicitly grant this nested lead authority to sub-delegate",
    )
    replaces_task_id: str | None = Field(
        default=None,
        description="rejected or cancelled required child this corrective task replaces",
    )
    files_to_touch: list[str] = Field(
        min_length=1,
        description="declared repo-relative POSIX paths for this child's coordination scope",
    )


class AssignTaskInput(BaseModel):
    """Arguments for ``assign_task`` — route one existing child task to a direct report."""

    task_id: str = Field(description="the id of an existing direct child task of the current task")
    assignee: str = Field(description="the employee id of the direct report who should own it")


class SubmitTaskTool(BaseTool):
    """Create one incremental child task and make the parent wait on it."""

    name = "submit_task"
    description = (
        "Create one follow-up child task for the current manager task, assign it to a direct "
        "report, and make the current task wait on it. Use this during integration when exactly "
        "one new piece of work is needed. Keep it a BIG chunk — a whole module or feature with its "
        "own tests; do not split by function, file, or layer."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = SubmitTaskInput

    def __init__(self, ledger: Ledger) -> None:
        self._service = CapabilityService(ledger)

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = SubmitTaskInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(content=f"refused: malformed submit_task input — {exc}", is_error=True)
        beat = BeatContext.read(ctx.working_dir)
        result = self._service.submit_one(
            parent_id=beat.task_id,
            revision=beat.run_id,
            actor_employee_id=beat.employee_id,
            child=ChildPlan(
                label=args.label,
                intent=args.intent,
                assignee=args.assignee,
                execution_mode=args.execution_mode,
                can_subdelegate=args.can_subdelegate,
                replaces_task_id=args.replaces_task_id,
                files_to_touch=tuple(args.files_to_touch),
            ),
        )
        if result.reviewer_assignees:
            joined = ", ".join(result.reviewer_assignees)
            return ToolResult(
                content=(
                    f"refused: {joined} is a reviewer — reviewers review, they don't own deliverable "
                    "tasks. No task created — assign it to an engineer report instead."
                ),
                structured={"reviewer_assignees": list(result.reviewer_assignees)},
                is_error=True,
            )
        if result.unknown_assignees:
            joined = ", ".join(result.unknown_assignees)
            return ToolResult(
                content=f"refused: not a direct report: {joined}. No task created.",
                structured={"unknown_assignees": list(result.unknown_assignees)},
                is_error=True,
            )
        if result.depth_capped:
            return ToolResult(
                content="refused: this task is at the delegation depth cap; no task created",
                structured={"depth_capped": True},
                is_error=True,
            )
        if result.authority_denied is not None:
            return ToolResult(
                content=f"refused: {result.authority_denied}; no task created",
                structured={"authority_denied": result.authority_denied},
                is_error=True,
            )
        if result.scope_violations:
            return ToolResult(
                content=_scope_refusal(result.scope_violations),
                structured={"scope_violations": _serialize_scope_violations(result.scope_violations)},
                is_error=True,
            )
        return ToolResult(
            content=f"created child task {result.child_id} and assigned it to {args.assignee}",
            structured={"child_id": result.child_id, "assignee": args.assignee},
        )


class AssignTaskTool(BaseTool):
    """Assign or reassign one existing direct child task to a direct report."""

    name = "assign_task"
    description = (
        "Assign one existing direct child task of the current manager task to a direct report. "
        "Use this to reroute unfinished child work during integration."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = AssignTaskInput

    def __init__(self, ledger: Ledger) -> None:
        self._service = CapabilityService(ledger)

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = AssignTaskInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(content=f"refused: malformed assign_task input — {exc}", is_error=True)
        beat = BeatContext.read(ctx.working_dir)
        result = self._service.reassign(
            parent_id=beat.task_id,
            task_id=args.task_id,
            assignee=args.assignee,
            assigned_by=beat.employee_id,
        )
        if result.unknown_assignee is not None:
            return ToolResult(
                content=f"refused: not a direct report: {result.unknown_assignee}. No assignment changed.",
                structured={"unknown_assignee": result.unknown_assignee},
                is_error=True,
            )
        if result.not_child:
            return ToolResult(
                content="refused: task is not a direct child of the current manager task",
                structured={"not_child": True},
                is_error=True,
            )
        if result.terminal_or_missing:
            return ToolResult(
                content="refused: task is missing or terminal; no assignment changed",
                structured={"terminal_or_missing": True},
                is_error=True,
            )
        if result.authority_denied is not None:
            return ToolResult(
                content=f"refused: {result.authority_denied}; no assignment changed",
                structured={"authority_denied": result.authority_denied},
                is_error=True,
            )
        return ToolResult(
            content=f"assigned {args.task_id} to {args.assignee}",
            structured={"task_id": args.task_id, "assignee": args.assignee},
        )


__all__ = ["AssignTaskInput", "AssignTaskTool", "SubmitTaskInput", "SubmitTaskTool"]


def _scope_refusal(violations: tuple[FileScopeViolation, ...]) -> str:
    joined = "; ".join(describe_file_scope_violation(violation) for violation in violations)
    return f"refused: invalid files_to_touch — {joined}. No task created."


def _serialize_scope_violations(
    violations: tuple[FileScopeViolation, ...],
) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for violation in violations:
        row = {"code": violation.code.value}
        if violation.task_id is not None:
            row["task_id"] = violation.task_id
        if violation.path is not None:
            row["path"] = violation.path
        if violation.other_task_id is not None:
            row["other_task_id"] = violation.other_task_id
        if violation.other_path is not None:
            row["other_path"] = violation.other_path
        payload.append(row)
    return payload
