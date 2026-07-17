"""Backlog verbs — submit/task/assign/eligible/decompose."""

from __future__ import annotations

from chorus.ids import mint_id
from chorus.ledger import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    SqliteLedger,
    Task,
    TaskPriority,
)
from chorus.lifecycle import (
    DEFAULT_REQUEST_DEPTH_CAP,
    ChildSpec,
    DepthCapped,
    assign_task,
    decompose,
)
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _fmt,
    _parse_limit,
    _parse_priority,
    _pop_flag,
    _preview,
)

_SUBMIT = "submit [--priority=LEVEL] <id> <intent...>"


@REGISTRY.command("submit", summary="create a task in the backlog", usage=_SUBMIT, hidden=True)
def _submit(ctx: CommandContext) -> LoopSignal:
    raw_priority, rest = _pop_flag(ctx.args, "priority")
    if len(rest) < 2:
        ctx.out.error(f"usage: {_SUBMIT}")
        return LoopSignal.CONTINUE
    priority = TaskPriority.MEDIUM
    if raw_priority is not None:
        parsed = _parse_priority(raw_priority, ctx.out)
        if parsed is None:
            return LoopSignal.CONTINUE
        priority = parsed
    task_id, intent = rest[0], " ".join(rest[1:])
    if ctx.session.ledger.tasks.get(task_id) is not None:
        ctx.out.error(f"task {task_id!r} already exists")
        return LoopSignal.CONTINUE
    created = ctx.session.ledger.tasks.submit(Task(id=task_id, intent=intent, priority=priority))
    ctx.out.line(f"submitted {created.id} ({created.status.value}, {created.priority.value})")
    return LoopSignal.CONTINUE


_TASK = "task <id>"


@REGISTRY.command("task", summary="show a task with its runs and DoD", usage=_TASK, hidden=True)
def _task(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_TASK}")
        return LoopSignal.CONTINUE
    ledger = ctx.session.ledger
    task = ledger.tasks.get(ctx.args[0])
    if task is None:
        ctx.out.error(f"no such task: {ctx.args[0]!r}")
        return LoopSignal.CONTINUE
    ctx.out.kv(
        {
            "id": task.id,
            "intent": task.intent,
            "status": task.status.value,
            "priority": task.priority.value,
            "assignee": _fmt(task.assignee_employee_id),
            "depth": task.depth,
            "parent": _fmt(task.parent_id),
        }
    )
    runs = ledger.runs.for_task(task.id)
    ctx.out.line("runs:")
    ctx.out.table(
        ("id", "employee", "status", "started", "finished"),
        [
            (run.id, run.employee_id, run.status.value, _fmt(run.started_at), _fmt(run.finished_at))
            for run in runs
        ],
    )
    dod = ledger.dod.get_for_task(task.id)
    if dod is not None:
        ctx.out.line(f"dod: {dod.kind} -- {dod.status.value}")
    return LoopSignal.CONTINUE


_ASSIGN = "assign <task_id> <employee_id>"


@REGISTRY.command(
    "assign", summary="assign a task and wake the employee", usage=_ASSIGN, hidden=True
)
def _assign(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 2:
        ctx.out.error(f"usage: {_ASSIGN}")
        return LoopSignal.CONTINUE
    task_id, employee_id = ctx.args
    if ctx.session.ledger.employees.get(employee_id) is None:
        ctx.out.error(f"no such employee: {employee_id!r} (hire them first)")
        return LoopSignal.CONTINUE
    wake = assign_task(ctx.session.ledger, task_id, employee_id)
    if wake is None:
        ctx.out.error(f"could not assign {task_id!r} (unknown or already terminal)")
        return LoopSignal.CONTINUE
    ctx.out.line(f"assigned {task_id} -> {employee_id}; woke {wake.id} ({wake.reason.value})")
    return LoopSignal.CONTINUE


_ELIGIBLE = "eligible [limit]"


@REGISTRY.command("eligible", summary="list tasks ready to dispatch", usage=_ELIGIBLE, hidden=True)
def _eligible(ctx: CommandContext) -> LoopSignal:
    limit = 20
    if ctx.args:
        parsed = _parse_limit(ctx.args[0], ctx.out)
        if parsed is None:
            return LoopSignal.CONTINUE
        limit = parsed
    tasks = ctx.session.ledger.tasks.list_eligible(limit=limit)
    ctx.out.table(
        ("id", "status", "priority", "assignee", "intent"),
        [
            (
                t.id,
                t.status.value,
                t.priority.value,
                _fmt(t.assignee_employee_id),
                _preview(t.intent),
            )
            for t in tasks
        ],
    )
    return LoopSignal.CONTINUE


def _accepted_plan(ledger: SqliteLedger, parent_id: str) -> str:
    """Record a minimal accepted plan revision the decomposition claim references (spec 02 §4)."""
    plan = Artifact(id=mint_id(), task_id=parent_id, type=ArtifactType.DOC)
    ledger.artifacts.create(plan)
    revision = ArtifactRevision(id=mint_id(), artifact_id=plan.id)
    ledger.artifact_revisions.record(revision)
    return revision.id


_DECOMPOSE = "decompose <parent_id> <child_intent...>"


@REGISTRY.command(
    "decompose",
    summary="manager fan-out: create a gated child (depth-capped)",
    usage=_DECOMPOSE,
    hidden=True,
)
def _decompose(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) < 2:
        ctx.out.error(f"usage: {_DECOMPOSE}")
        return LoopSignal.CONTINUE
    parent_id, child_intent = ctx.args[0], " ".join(ctx.args[1:])
    ledger = ctx.session.ledger
    if ledger.tasks.get(parent_id) is None:
        ctx.out.error(f"no such task: {parent_id!r}")
        return LoopSignal.CONTINUE
    revision_id = _accepted_plan(ledger, parent_id)  # the manager's accepted plan (spec 02 §4)
    child = Task(id=mint_id(), intent=child_intent)
    outcome = decompose(
        ledger,
        source_task_id=parent_id,
        accepted_plan_revision_id=revision_id,
        children=[ChildSpec(task=child, gates_parent=True)],
        request_depth_cap=DEFAULT_REQUEST_DEPTH_CAP,
    )
    if isinstance(outcome, DepthCapped):
        ctx.out.error(
            f"decompose refused: {parent_id} is at the delegation depth cap "
            f"({DEFAULT_REQUEST_DEPTH_CAP}) -- task blocked, recovery {outcome.recovery.id} opened"
        )
        return LoopSignal.CONTINUE
    ctx.out.line(f"decomposed {parent_id} -> {child.id} ({child_intent})")
    return LoopSignal.CONTINUE


# -- coordination -----------------------------------------------------------------------------------
