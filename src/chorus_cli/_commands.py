"""The console's verbs — every command the ledger console exposes today.

Each handler is a small, pure function over :class:`CommandContext`: it validates its arguments,
calls the **real** chorus ledger/lifecycle layer, and renders the result. Only operations that work
end-to-end today are here — seed the workforce, submit and assign tasks, pass messages, and inspect
the durable state. Running beats needs a configured dream beat runner (see ``examples/real_beat.py``)
and is intentionally out of this console.

Commands register themselves into :data:`REGISTRY` at import time via the ``@REGISTRY.command``
decorator, so the verb table is assembled declaratively in one file.
"""

from __future__ import annotations

import uuid

from chorus.ledger import Message, MessageKind, Task, TaskPriority
from chorus.lifecycle import assign_task, deliver_message
from chorus.workforce import Employee
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli._registry import CommandRegistry
from chorus_cli._render import Console

REGISTRY = CommandRegistry()

_PREVIEW = 48  # how many chars of free text (intent/body) a table cell shows
_OPERATOR = "operator"  # the human at the console — the sender of messages it delivers


def _fmt(value: object) -> str:
    """Render an optional field: ``-`` for ``None``, otherwise its string form."""
    return "-" if value is None else str(value)


def _preview(text: str) -> str:
    """One-line, length-capped preview of free text for a table cell."""
    flat = text.replace("\n", " ").strip()
    return flat if len(flat) <= _PREVIEW else flat[: _PREVIEW - 1] + "…"


def _parse_priority(raw: str, out: Console) -> TaskPriority | None:
    """Convert a user string to :class:`TaskPriority` at the boundary, or report and return ``None``."""
    try:
        return TaskPriority(raw)
    except ValueError:
        choices = ", ".join(level.value for level in TaskPriority)
        out.error(f"unknown priority {raw!r}; choose one of: {choices}")
        return None


def _parse_limit(raw: str, out: Console) -> int | None:
    """Parse a positive integer limit, or report and return ``None``."""
    try:
        value = int(raw)
    except ValueError:
        out.error(f"{raw!r} is not an integer")
        return None
    if value < 1:
        out.error(f"limit must be a positive integer, got {value}")
        return None
    return value


def _pop_flag(args: tuple[str, ...], name: str) -> tuple[str | None, tuple[str, ...]]:
    """Pull a ``--name`` flag out of ``args``; return ``(value | None, remaining_args)``.

    Accepts both joined (``--name=value``) and space-separated (``--name value``) forms — the two
    conventions a user reasonably types — and leaves everything else in ``rest``.
    """
    joined = f"--{name}="
    bare = f"--{name}"
    value: str | None = None
    rest: list[str] = []
    index = 0
    while index < len(args):
        arg = args[index]
        if arg.startswith(joined):
            value = arg[len(joined) :]
        elif arg == bare and index + 1 < len(args):
            value = args[index + 1]
            index += 1  # consume the following value token
        else:
            rest.append(arg)
        index += 1
    return value, tuple(rest)


# -- meta -------------------------------------------------------------------------------------------

_HELP = "help [command]"


@REGISTRY.command("help", summary="list commands, or show usage for one", usage=_HELP)
def _help(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        target = REGISTRY.get(ctx.args[0])
        if target is None:
            ctx.out.error(f"unknown command: {ctx.args[0]!r}")
            return LoopSignal.CONTINUE
        ctx.out.kv({"command": target.name, "usage": target.usage, "summary": target.summary})
        return LoopSignal.CONTINUE
    ctx.out.table(
        ("command", "summary"),
        [(command.name, command.summary) for command in REGISTRY.visible()],
    )
    return LoopSignal.CONTINUE


_QUIT = "quit"


@REGISTRY.command("quit", summary="leave the console", usage=_QUIT)
def _quit(ctx: CommandContext) -> LoopSignal:
    return LoopSignal.QUIT


# -- workforce --------------------------------------------------------------------------------------

_HIRE = "hire <id> <name> <role> [reports_to]"


@REGISTRY.command("hire", summary="add an employee to the ledger", usage=_HIRE)
def _hire(ctx: CommandContext) -> LoopSignal:
    if not 3 <= len(ctx.args) <= 4:
        ctx.out.error(f"usage: {_HIRE}")
        return LoopSignal.CONTINUE
    employee_id, name, role = ctx.args[0], ctx.args[1], ctx.args[2]
    if ctx.session.ledger.employees.get(employee_id) is not None:
        ctx.out.error(f"employee {employee_id!r} already exists")
        return LoopSignal.CONTINUE
    reports_to = ctx.args[3] if len(ctx.args) == 4 else None
    created = ctx.session.ledger.employees.create(
        Employee(id=employee_id, name=name, role=role, reports_to=reports_to)
    )
    ctx.out.line(f"hired {created.id} ({created.role}) — status {created.status.value}")
    return LoopSignal.CONTINUE


_EMPLOYEE = "employee <id>"


@REGISTRY.command("employee", summary="show one employee", usage=_EMPLOYEE)
def _employee(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_EMPLOYEE}")
        return LoopSignal.CONTINUE
    employee = ctx.session.ledger.employees.get(ctx.args[0])
    if employee is None:
        ctx.out.error(f"no such employee: {ctx.args[0]!r}")
        return LoopSignal.CONTINUE
    ctx.out.kv(
        {
            "id": employee.id,
            "name": employee.name,
            "role": employee.role,
            "reports_to": _fmt(employee.reports_to),
            "status": employee.status.value,
            "spent_cents": employee.spent_monthly_cents,
        }
    )
    return LoopSignal.CONTINUE


# -- tasks ------------------------------------------------------------------------------------------

_SUBMIT = "submit [--priority=LEVEL] <id> <intent...>"


@REGISTRY.command("submit", summary="create a task in the backlog", usage=_SUBMIT)
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
    created = ctx.session.ledger.tasks.submit(
        Task(id=task_id, intent=intent, priority=priority)
    )
    ctx.out.line(
        f"submitted {created.id} ({created.status.value}, {created.priority.value})"
    )
    return LoopSignal.CONTINUE


_TASK = "task <id>"


@REGISTRY.command("task", summary="show a task with its runs and DoD", usage=_TASK)
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
        ctx.out.line(f"dod: {dod.kind} — {dod.status.value}")
    return LoopSignal.CONTINUE


_ASSIGN = "assign <task_id> <employee_id>"


@REGISTRY.command("assign", summary="assign a task and wake the employee", usage=_ASSIGN)
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
    ctx.out.line(f"assigned {task_id} → {employee_id}; woke {wake.id} ({wake.reason.value})")
    return LoopSignal.CONTINUE


_ELIGIBLE = "eligible [limit]"


@REGISTRY.command("eligible", summary="list tasks ready to dispatch", usage=_ELIGIBLE)
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
            (t.id, t.status.value, t.priority.value, _fmt(t.assignee_employee_id), _preview(t.intent))
            for t in tasks
        ],
    )
    return LoopSignal.CONTINUE


# -- coordination -----------------------------------------------------------------------------------

_WAKES = "wakes"


@REGISTRY.command("wakes", summary="list queued wakes", usage=_WAKES)
def _wakes(ctx: CommandContext) -> LoopSignal:
    queued = ctx.session.ledger.wakes.queued()
    ctx.out.table(
        ("id", "employee", "reason", "task"),
        [
            (wake.id, wake.employee_id, wake.reason.value, _fmt(wake.payload.get("task_id")))
            for wake in queued
        ],
    )
    return LoopSignal.CONTINUE


_MESSAGE = "message <to_employee_id> <body...>"


@REGISTRY.command("message", summary="deliver a message and wake the recipient", usage=_MESSAGE)
def _message(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) < 2:
        ctx.out.error(f"usage: {_MESSAGE}")
        return LoopSignal.CONTINUE
    to_employee_id, body = ctx.args[0], " ".join(ctx.args[1:])
    if ctx.session.ledger.employees.get(to_employee_id) is None:
        ctx.out.error(f"no such employee: {to_employee_id!r} (hire them first)")
        return LoopSignal.CONTINUE
    wake = deliver_message(
        ctx.session.ledger,
        Message(
            id=f"msg_{uuid.uuid4().hex[:12]}",
            to_employee_id=to_employee_id,
            body=body,
            kind=MessageKind.INSTRUCTION,
            from_user_id=_OPERATOR,  # the console operator is the sender (ledger requires exactly one)
        ),
    )
    ctx.out.line(f"delivered to {to_employee_id}; woke {wake.id} ({wake.reason.value})")
    return LoopSignal.CONTINUE


_INBOX = "inbox <employee_id>"


@REGISTRY.command("inbox", summary="show an employee's unread mailbox", usage=_INBOX)
def _inbox(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_INBOX}")
        return LoopSignal.CONTINUE
    messages = ctx.session.ledger.messages.inbox(ctx.args[0])
    ctx.out.table(
        ("id", "from", "kind", "body"),
        [
            (m.id, _fmt(m.from_employee_id or m.from_user_id), m.kind.value, _preview(m.body))
            for m in messages
        ],
    )
    return LoopSignal.CONTINUE


# -- the kernel -------------------------------------------------------------------------------------

_TICK = "tick"


@REGISTRY.command(
    "tick", summary="run one kernel pulse — dispatch a real beat (needs Azure keys)", usage=_TICK
)
def _tick(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        ctx.out.error(f"usage: {_TICK}")
        return LoopSignal.CONTINUE
    beats = ctx.session.beats
    if beats is None:
        ctx.out.error(
            "no beat runner configured — set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, "
            "AZURE_OPENAI_DEPLOYMENT and relaunch"
        )
        return LoopSignal.CONTINUE
    ctx.out.line(f"ticking the kernel (model {beats.model}) — this runs a real beat, please wait…")
    report = beats.run_tick()
    ctx.out.kv(
        {
            "recovered": report.recovered,
            "routines_fired": report.routines_fired,
            "wakes_dispatched": report.wakes_dispatched,
            "beats_started": report.beats_started,
            "blocked_by_budget": report.blocked_by_budget,
        }
    )
    if report.beats_started:
        ctx.out.line("a beat ran — see how it landed with 'task <id>'")
    else:
        ctx.out.line("nothing to dispatch (assign a task first, then tick)")
    return LoopSignal.CONTINUE


# -- accounting -------------------------------------------------------------------------------------

_COST = "cost <employee_id>"


@REGISTRY.command("cost", summary="show an employee's recorded spend", usage=_COST)
def _cost(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_COST}")
        return LoopSignal.CONTINUE
    spent = ctx.session.ledger.cost_events.spent_cents(ctx.args[0])
    ctx.out.line(f"{ctx.args[0]} has spent {spent} cents")
    return LoopSignal.CONTINUE


_SCHEMA = "schema"


@REGISTRY.command("schema", summary="show the ledger schema version", usage=_SCHEMA)
def _schema(ctx: CommandContext) -> LoopSignal:
    ctx.out.line(f"schema version: {_fmt(ctx.session.ledger.schema_version())}")
    return LoopSignal.CONTINUE


REGISTRY.alias("?", of="help")
REGISTRY.alias("exit", of="quit")


__all__ = ["REGISTRY"]
