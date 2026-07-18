"""Comment tools — tasks + comments as the coordination channel (OM-3, paperclip's model).

There is no chat: coordination is a comment on a task, and an employee's inbox is its assigned
tasks + the comments on them. A comment is a task-anchored ``message`` row delivered through
:func:`chorus.lifecycle.deliver_message` — it runs nothing; the recipient's next beat sees it
(the wake coalesces per recipient). Recipient resolution is structural: the task's assignee,
else up the chain (parent task's assignee, then the task's creator) — never into the void.
"""

from __future__ import annotations

import uuid

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger, Message, MessageKind, Task


class CommentInput(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    task_id: str | None = Field(
        default=None, description="The task to comment on; defaults to the current beat's task."
    )


class ReadCommentsInput(BaseModel):
    task_id: str | None = Field(
        default=None, description="The task whose thread to read; defaults to the beat's task."
    )


def _resolve_task(ledger: Ledger, ctx: ToolExecutionContext, task_id: str | None) -> Task | None:
    beat = BeatContext.read(ctx.working_dir)
    resolved = task_id or beat.task_id
    return ledger.tasks.get(resolved) if resolved else None


def _recipient(ledger: Ledger, task: Task, author: str) -> str | None:
    """The comment's structural recipient: assignee, else parent assignee, else creator."""
    candidates = [task.assignee_employee_id]
    parent = ledger.tasks.get(task.parent_id) if task.parent_id else None
    if parent is not None:
        candidates.append(parent.assignee_employee_id)
    candidates.append(task.created_by_employee_id)
    for candidate in candidates:
        if candidate is not None and candidate != author:
            return candidate
    return None


class CommentTool(BaseTool):
    """Leave a comment on a task; the person it concerns is woken to read it."""

    name = "comment"
    description = (
        "Comment on a task (defaults to your current task). Use this to coordinate: report a "
        "blocker, ask a question, or leave context for whoever the task concerns. The comment "
        "notifies the task's assignee — or, when you are the assignee, your manager up the "
        "chain. A comment never runs anything."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = CommentInput

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        payload = CommentInput.model_validate(input)
        beat = BeatContext.read(ctx.working_dir)
        task = _resolve_task(self._ledger, ctx, payload.task_id)
        if task is None:
            return _refused("the task to comment on was not found")
        recipient = _recipient(self._ledger, task, beat.employee_id)
        if recipient is None:
            return _refused("no recipient: the task has no assignee, parent assignee, or creator")
        from chorus.lifecycle import deliver_message

        message = deliver_message(
            self._ledger,
            Message(
                id=str(uuid.uuid4()),
                from_employee_id=beat.employee_id,
                to_employee_id=recipient,
                task_id=task.id,
                body=payload.body,
                kind=MessageKind.REPLY,
            ),
        )
        return ToolResult(
            content=f"comment left on task {task.id}; {recipient} will see it on their next beat",
            structured={"status": "success", "task_id": task.id, "notified": recipient,
                        "wake_id": message.id},
        )


class ReadCommentsTool(BaseTool):
    """Read a task's comment thread — shared context, oldest first."""

    name = "read_comments"
    description = (
        "Read the comment thread on a task (defaults to your current task): who said what, in "
        "order. Read this before starting work a comment may have re-scoped."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=10.0)
    input_model = ReadCommentsInput

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        payload = ReadCommentsInput.model_validate(input)
        task = _resolve_task(self._ledger, ctx, payload.task_id)
        if task is None:
            return _refused("the task whose thread to read was not found")
        comments = [
            {
                "author": m.from_employee_id or m.from_user_id,
                "body": m.body,
                "at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in self._ledger.messages.for_task(task.id)
        ]
        return ToolResult(
            content=f"{len(comments)} comment(s) on task {task.id}",
            structured={"status": "success", "task_id": task.id, "comments": comments},
        )


def _refused(reason: str) -> ToolResult:
    return ToolResult(
        content=f"refused: {reason}",
        structured={"status": "refused", "reason": reason},
        is_error=True,
    )


__all__ = ["CommentInput", "CommentTool", "ReadCommentsInput", "ReadCommentsTool"]
