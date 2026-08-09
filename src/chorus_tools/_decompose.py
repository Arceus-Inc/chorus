"""The chorus ``decompose`` capability, exposed to the model as a dream tool (spec 02 §4, 06 §4, M3).

This is the composition seam that makes a chorus capability **model-callable**: a manager agent calls
``decompose`` during its beat, and chorus fans the current task out into real ledger children, each
assigned to a named report. The tool is a thin dream envelope around
:class:`~chorus.lifecycle.CapabilityService` — it validates the model's children DAG and reads the
per-beat :class:`~chorus.heartbeat.BeatContext` from ``ctx.working_dir`` (which task / run it is acting
for), then delegates the mutation. Core ``chorus`` stays dream-free; the dream import lives here in
``chorus_tools`` (a composition layer, like ``chorus_cli``).
"""

from __future__ import annotations

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.ledger import ExecutionMode, Ledger
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.lifecycle._file_scope import FileScopeViolation, describe_file_scope_violation


class _ChildInput(BaseModel):
    """One subtask the manager proposes, routed to one report."""

    label: str = Field(
        description="a short stable name for this subtask, unique in this call (e.g. 'api')"
    )
    intent: str = Field(description="what the subtask should accomplish")
    assignee: str = Field(description="the employee id of the report who will own this subtask")
    execution_mode: ExecutionMode = Field(
        default=ExecutionMode.DELIVERY,
        description="delivery for specialist work, delegation for a nested management assignment",
    )
    can_subdelegate: bool = Field(
        default=False,
        description="explicitly grant this nested lead authority to sub-delegate",
    )
    depends_on: list[str] = Field(
        default_factory=list,
        description="labels of sibling subtasks in this call that must finish before this one starts",
    )
    files_to_touch: list[str] = Field(
        min_length=1,
        description="declared repo-relative POSIX paths for this subtask's coordination scope",
    )


class DecomposeInput(BaseModel):
    """Arguments for ``decompose`` — every subtask of the fan-out in one call."""

    children: list[_ChildInput] = Field(description="the subtasks to fan the current task out into")


class DecomposeTool(BaseTool):
    """Split the current task into assigned subtasks via chorus ``decompose`` (depth-capped, idempotent)."""

    name = "decompose"
    description = (
        "Split the current task into concrete subtasks and assign each to a report. Call once with "
        "every subtask in 'children'; use 'depends_on' to order them. Keep each subtask a BIG chunk — "
        "a whole module or feature the owner builds end to end with its own tests in one beat; do not "
        "split a module by function, file, or layer, and do not create plan-only or test-only "
        "subtasks. The current task then waits on the whole subtree. Refused if the task is already at "
        "the delegation depth cap."
    )
    # tier_required=1 (REPO_WRITE): a mutating tool is gated as a write effect, so its *trusted* tier
    # (from this declaration, since it registers DEFAULT/built-in) must meet that — else dream denies it
    # ("not trusted for write"). The manager's REPO_WRITE session tier then admits it.
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = DecomposeInput

    def __init__(self, ledger: Ledger) -> None:
        self._service = CapabilityService(ledger)

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = DecomposeInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(content=f"refused: malformed decompose input — {exc}", is_error=True)
        rejection = _validate(args)
        if rejection is not None:
            return ToolResult(content=rejection, is_error=True)

        beat = BeatContext.read(ctx.working_dir)
        plans = [
            ChildPlan(
                label=child.label,
                intent=child.intent,
                assignee=child.assignee,
                depends_on=tuple(child.depends_on),
                execution_mode=child.execution_mode,
                can_subdelegate=child.can_subdelegate,
                files_to_touch=tuple(child.files_to_touch),
            )
            for child in args.children
        ]
        result = self._service.decompose(
            parent_id=beat.task_id,
            revision=beat.run_id,
            children=plans,
            actor_employee_id=beat.employee_id,
        )
        if result.reviewer_assignees:
            joined = ", ".join(result.reviewer_assignees)
            return ToolResult(
                content=(
                    f"refused: {joined} is a reviewer — reviewers review your team's work, they don't "
                    "own deliverable tasks. No subtasks created — assign build / test / quality work to "
                    "an engineer report and call decompose again."
                ),
                is_error=True,
                structured={"reviewer_assignees": list(result.reviewer_assignees)},
            )
        if result.unknown_assignees:
            joined = ", ".join(result.unknown_assignees)
            return ToolResult(
                content=(
                    f"refused: not a direct report: {joined}. No subtasks created — assign each "
                    "child to one of your reports by their employee id, then call decompose again."
                ),
                is_error=True,
                structured={"unknown_assignees": list(result.unknown_assignees)},
            )
        if result.depth_capped:
            return ToolResult(
                content=(
                    "refused: this task is at the delegation depth cap; "
                    "no subtasks created and the task is now blocked"
                ),
                structured={"depth_capped": True},
            )
        if result.authority_denied is not None:
            return ToolResult(
                content=f"refused: {result.authority_denied}; no subtasks created",
                structured={"authority_denied": result.authority_denied},
                is_error=True,
            )
        if result.scope_violations:
            return ToolResult(
                content=_scope_refusal(result.scope_violations),
                structured={"scope_violations": _serialize_scope_violations(result.scope_violations)},
                is_error=True,
            )
        listing = ", ".join(f"{c.label}→{c.assignee}" for c in args.children)
        return ToolResult(
            content=f"created {len(plans)} subtasks: {listing}",
            structured={"depth_capped": False, "children": result.child_ids},
        )


def _validate(args: DecomposeInput) -> str | None:
    """Return a rejection message if the children DAG is malformed, else ``None``."""
    if not args.children:
        return "provide at least one subtask in 'children'"
    labels = [child.label for child in args.children]
    if len(set(labels)) != len(labels):
        return "each subtask 'label' must be unique within the call"
    known = set(labels)
    for child in args.children:
        unknown = [dep for dep in child.depends_on if dep not in known]
        if unknown:
            return f"subtask {child.label!r} depends on unknown label(s): {', '.join(unknown)}"
    return None


def _scope_refusal(violations: tuple[FileScopeViolation, ...]) -> str:
    joined = "; ".join(describe_file_scope_violation(violation) for violation in violations)
    return f"refused: invalid files_to_touch — {joined}. No subtasks created."


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


__all__ = ["DecomposeInput", "DecomposeTool"]
