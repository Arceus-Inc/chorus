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

import os
import sqlite3
import uuid

from chorus.budgets import BudgetEnforcer, BudgetWindow, window_start
from chorus.errors import OrgInvariantViolation, UnknownEmployee
from chorus.governance import GovernanceError, GovernanceResolver
from chorus.ledger import (
    ApprovalGate,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
    Message,
    MessageKind,
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
    deliver_message,
)
from chorus.outcomes import DoDKind, Verifier
from chorus.workforce import EmployeeStatus, GitWorkforce, LedgerWorkforce, copy_org
from chorus.workspace import CompanyWorkspace, WorkspaceError, default_work_root
from chorus_cli._chat import ChatRenderBus, run_chat
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

_HIRE = "hire <name> <role> [reports_to]"


@REGISTRY.command("hire", summary="add an employee to the workforce", usage=_HIRE)
def _hire(ctx: CommandContext) -> LoopSignal:
    if not 2 <= len(ctx.args) <= 3:
        ctx.out.error(f"usage: {_HIRE}")
        return LoopSignal.CONTINUE
    name, role = ctx.args[0], ctx.args[1]
    reports_to = ctx.args[2] if len(ctx.args) == 3 else None
    workforce = LedgerWorkforce(ctx.session.ledger.employees)
    try:
        created = workforce.hire(name=name, role=role, reports_to=reports_to)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ctx.out.line(f"hired {created.id} ({created.role}) -- status {created.status.value}")
    return LoopSignal.CONTINUE


_TERMINATE = "terminate <id>"


@REGISTRY.command("terminate", summary="irreversibly terminate an employee", usage=_TERMINATE)
def _terminate(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_TERMINATE}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    ledger = ctx.session.ledger
    try:
        LedgerWorkforce(ledger.employees).terminate(employee_id)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ledger.runs.cancel_running(employee_id=employee_id)
    ledger.wakes.drop_queued(employee_id=employee_id)
    ctx.out.line(f"terminated {employee_id} -- cancelled its runs + dropped queued wakes")
    return LoopSignal.CONTINUE


_PAUSE = "pause <id>"


@REGISTRY.command("pause", summary="pause an employee (the gate holds its wakes)", usage=_PAUSE)
def _pause(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_PAUSE}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    employees = ctx.session.ledger.employees
    if employees.get(employee_id) is None:
        ctx.out.error(f"no such employee: {employee_id!r}")
        return LoopSignal.CONTINUE
    employees.set_status(employee_id, EmployeeStatus.PAUSED)
    ctx.out.line(f"paused {employee_id}")
    return LoopSignal.CONTINUE


_RESUME = "resume <id>"


@REGISTRY.command("resume", summary="resume a paused employee", usage=_RESUME)
def _resume(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_RESUME}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    employees = ctx.session.ledger.employees
    employee = employees.get(employee_id)
    if employee is None:
        ctx.out.error(f"no such employee: {employee_id!r}")
        return LoopSignal.CONTINUE
    if employee.status is EmployeeStatus.TERMINATED:
        ctx.out.error(f"{employee_id!r} is terminated -- termination is irreversible")
        return LoopSignal.CONTINUE
    employees.set_status(employee_id, EmployeeStatus.IDLE)
    ctx.out.line(f"resumed {employee_id} -- status idle")
    return LoopSignal.CONTINUE


_WORKFORCE = "workforce"


@REGISTRY.command("workforce", summary="list the org (every employee + status)", usage=_WORKFORCE)
def _workforce(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        ctx.out.error(f"usage: {_WORKFORCE}")
        return LoopSignal.CONTINUE
    employees = ctx.session.ledger.employees.list()
    ctx.out.table(
        ("id", "name", "role", "reports_to", "status"),
        [
            (e.id, e.name, e.role, _fmt(e.reports_to), e.status.value)
            for e in employees
        ],
    )
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


_EXPORT = "export <dir>"


@REGISTRY.command("export", summary="serialize the org to a git-markdown tree", usage=_EXPORT)
def _export(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_EXPORT}")
        return LoopSignal.CONTINUE
    org_repo = ctx.args[0]
    live = LedgerWorkforce(ctx.session.ledger.employees)
    count = copy_org(live, GitWorkforce(org_repo))
    ctx.out.line(f"exported {count} employees to {org_repo}/employees/")
    return LoopSignal.CONTINUE


_IMPORT = "import <dir>"


@REGISTRY.command("import", summary="materialize a git-markdown org into the ledger", usage=_IMPORT)
def _import(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_IMPORT}")
        return LoopSignal.CONTINUE
    org_repo = ctx.args[0]
    live = LedgerWorkforce(ctx.session.ledger.employees)
    try:
        count = copy_org(GitWorkforce(org_repo), live)
    except (OrgInvariantViolation, UnknownEmployee) as exc:
        ctx.out.error(f"import failed: {exc}")
        return LoopSignal.CONTINUE
    ctx.out.line(f"imported {count} employees from {org_repo}")
    return LoopSignal.CONTINUE


# -- company workspace ------------------------------------------------------------------------------

_COMPANY = "company [init [seed]]"


@REGISTRY.command("company", summary="show or create the company workspace (the shared git root)", usage=_COMPANY)
def _company(ctx: CommandContext) -> LoopSignal:
    """Show or create ``.chorus/work/{company}/repo`` — the ``main`` employees' worktrees branch from.

    ``company`` shows the workspace status; ``company init [seed]`` creates it (idempotent). ``tick`` /
    ``chat`` create it lazily anyway, but this makes it explicit and lets you seed from a real repo up
    front. ``seed`` is a git repo path, a clone URL, or a plain directory; it falls back to
    ``CHORUS_COMPANY_SEED`` when omitted, matching what ``tick`` / ``chat`` read.
    """
    company_id = ctx.session.company_id
    root = default_work_root() / company_id
    sub = ctx.args[0] if ctx.args else "show"
    if sub == "show":
        repo = root / "repo"
        ctx.out.kv(
            {
                "company": company_id,
                "root": str(root),
                "created": "yes" if (repo / ".git").exists() else "no",
            }
        )
        return LoopSignal.CONTINUE
    if sub == "init":
        seed = ctx.args[1] if len(ctx.args) > 1 else (os.environ.get("CHORUS_COMPANY_SEED") or None)
        try:
            repo = CompanyWorkspace(root, seed=seed).ensure_repo()
        except WorkspaceError as exc:
            ctx.out.error(f"company init failed: {exc}")
            return LoopSignal.CONTINUE
        seeded = f", seeded from {seed}" if seed else ""
        ctx.out.line(f"company {company_id!r} ready at {repo} (branch main{seeded})")
        return LoopSignal.CONTINUE
    ctx.out.error(f"usage: {_COMPANY}")
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
        ctx.out.line(f"dod: {dod.kind} -- {dod.status.value}")
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
    ctx.out.line(f"assigned {task_id} -> {employee_id}; woke {wake.id} ({wake.reason.value})")
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


def _accepted_plan(ledger: SqliteLedger, parent_id: str) -> str:
    """Record a minimal accepted plan revision the decomposition claim references (spec 02 §4)."""
    plan = Artifact(id=f"plan_{uuid.uuid4().hex[:12]}", task_id=parent_id, type=ArtifactType.DOC)
    ledger.artifacts.create(plan)
    revision = ArtifactRevision(id=f"rev_{uuid.uuid4().hex[:12]}", artifact_id=plan.id)
    ledger.artifact_revisions.record(revision)
    return revision.id


_DECOMPOSE = "decompose <parent_id> <child_intent...>"


@REGISTRY.command("decompose", summary="manager fan-out: create a gated child (depth-capped)", usage=_DECOMPOSE)
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
    child = Task(id=f"task_{uuid.uuid4().hex[:12]}", intent=child_intent)
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
    "tick", summary="run one kernel pulse -- dispatch a real beat (needs Azure keys)", usage=_TICK
)
def _tick(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        ctx.out.error(f"usage: {_TICK}")
        return LoopSignal.CONTINUE
    beats = ctx.session.beats
    if beats is None:
        ctx.out.error(
            "no beat runner configured -- set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, "
            "AZURE_OPENAI_DEPLOYMENT and relaunch"
        )
        return LoopSignal.CONTINUE
    ctx.out.line(f"ticking the kernel (model {beats.model}) -- this runs a real beat, please wait...")
    report = beats.run_tick()
    ctx.out.kv(
        {
            "recovered": report.recovered,
            "routines_fired": report.routines_fired,
            "wakes_dispatched": report.wakes_dispatched,
            "beats_started": report.beats_started,
            "blocked_by_concurrency": report.blocked_by_budget,
            "gated_by_budget": report.budget_gated,
        }
    )
    if report.beats_started:
        ctx.out.line("a beat ran -- see how it landed with 'task <id>'")
    elif report.budget_gated:
        ctx.out.line("a dispatch was gated by a budget -- see 'budget' (raise to resume)")
    else:
        ctx.out.line("nothing to dispatch (assign a task first, then tick)")
    return LoopSignal.CONTINUE


_CHAT = "chat <employee_id>"


@REGISTRY.command(
    "chat", summary="converse with an employee -- each line runs a real beat (needs Azure keys)", usage=_CHAT
)
def _chat(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_CHAT}")
        return LoopSignal.CONTINUE
    employee_id = ctx.args[0]
    employee = ctx.session.ledger.employees.get(employee_id)
    if employee is None:
        ctx.out.error(f"no such employee: {employee_id!r} (hire them first)")
        return LoopSignal.CONTINUE
    if employee.status is EmployeeStatus.TERMINATED:
        ctx.out.error(f"{employee_id!r} is terminated -- termination is irreversible")
        return LoopSignal.CONTINUE
    # The render bus shares the console's stream so the streamed reply and the footer interleave.
    render_bus = ChatRenderBus(ctx.out.out, colour=ctx.out.colour)
    # dream is imported lazily here (only when chatting) so the keys-free console never pays for it.
    from chorus_cli._beats import chat_service_from_env

    service = chat_service_from_env(
        ctx.session.ledger,
        employee_id=employee_id,
        render_bus=render_bus,
        company_id=ctx.session.company_id,
    )
    if service is None:
        ctx.out.error(
            "no beat runner configured -- set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, "
            "AZURE_OPENAI_DEPLOYMENT and relaunch"
        )
        return LoopSignal.CONTINUE
    if employee.status is EmployeeStatus.PAUSED:
        ctx.out.line(f"note: {employee_id} is paused -- its turns will be gated until you 'resume' it")
    run_chat(
        employee_id,
        ledger=ctx.session.ledger,
        service=service,
        render_bus=render_bus,
        console=ctx.out,
        input_func=ctx.session.input_func,
    )
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


# -- budgets (spec 04 §3) ---------------------------------------------------------------------------

_DEFAULT_WARN = 80
_DEFAULT_WINDOW = "monthly"


def _parse_amount(raw: str, out: Console) -> int | None:
    """Parse a positive integer cent amount, or report and return ``None``."""
    try:
        value = int(raw)
    except ValueError:
        out.error(f"{raw!r} is not an integer (cents)")
        return None
    if value < 1:
        out.error(f"amount must be a positive integer, got {value}")
        return None
    return value


def _parse_scope(raw: str, out: Console) -> BudgetScope | None:
    """Convert a user string to :class:`BudgetScope` at the boundary, or report and return ``None``."""
    try:
        return BudgetScope(raw)
    except ValueError:
        choices = ", ".join(scope.value for scope in BudgetScope)
        out.error(f"unknown scope {raw!r}; choose one of: {choices}")
        return None


def _parse_window(raw: str, out: Console) -> BudgetWindow | None:
    try:
        return BudgetWindow(raw)
    except ValueError:
        choices = ", ".join(window.value for window in BudgetWindow)
        out.error(f"unknown window {raw!r}; choose one of: {choices}")
        return None


def _spent_for(ctx: CommandContext, policy: BudgetPolicy) -> int:
    """Live spend for a policy within its window — employee scope or the whole company."""
    start = window_start(BudgetWindow(policy.window_kind), ctx.session.clock())
    if policy.scope_type is BudgetScope.EMPLOYEE:
        return ctx.session.ledger.cost_events.spent_cents(policy.scope_id, since=start)
    return ctx.session.ledger.cost_events.total_spent_cents(since=start)


def _budget_status(ctx: CommandContext, policy: BudgetPolicy, spent: int) -> str:
    """``paused`` (open hard incident) / ``over`` / ``warn`` / ``ok`` for the dashboard."""
    incidents = ctx.session.ledger.budget_incidents.open_for_policy(policy.id)
    if any(i.threshold_type is BudgetThreshold.HARD for i in incidents):
        return "paused"
    if policy.hard_stop_enabled and spent >= policy.amount:
        return "over"
    if spent >= policy.amount * policy.warn_percent // 100:
        return "warn"
    return "ok"


def _enforcer(ctx: CommandContext) -> BudgetEnforcer:
    return BudgetEnforcer(ctx.session.ledger, company_id=ctx.session.company_id)


def _budget_list(ctx: CommandContext) -> LoopSignal:
    ledger = ctx.session.ledger
    policies = ledger.budget_policies.all()
    if not policies:
        ctx.out.line("no budgets -- 'budget set employee <id> <cents>' or 'budget set company <cents>'")
        return LoopSignal.CONTINUE
    rows = []
    for policy in policies:
        spent = _spent_for(ctx, policy)
        pct = f"{spent * 100 // policy.amount}%" if policy.amount else "-"
        rows.append((policy.id, policy.scope_type.value, policy.scope_id, policy.amount, spent,
                     pct, policy.window_kind, _budget_status(ctx, policy, spent)))
    ctx.out.table(("policy", "scope", "id", "cap_cents", "spent_cents", "used", "window", "status"), rows)
    incidents = [i for p in policies for i in ledger.budget_incidents.open_for_policy(p.id)]
    if incidents:
        ctx.out.line("open incidents:")
        ctx.out.table(
            ("incident", "policy", "threshold", "observed_cents", "approval"),
            [(i.id, i.policy_id, i.threshold_type.value, i.amount_observed, _fmt(i.approval_id))
             for i in incidents],
        )
    return LoopSignal.CONTINUE


def _budget_set(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    raw_warn, args = _pop_flag(args, "warn")
    raw_window, args = _pop_flag(args, "window")
    if not args:
        ctx.out.error(f"usage: {_BUDGET_SET}")
        return LoopSignal.CONTINUE
    scope = _parse_scope(args[0], ctx.out)
    if scope is None:
        return LoopSignal.CONTINUE
    if scope is BudgetScope.COMPANY:
        if len(args) != 2:
            ctx.out.error(f"usage: {_BUDGET_SET}")
            return LoopSignal.CONTINUE
        scope_id, raw_amount = ctx.session.company_id, args[1]
    else:
        if len(args) != 3:
            ctx.out.error(f"usage: {_BUDGET_SET}")
            return LoopSignal.CONTINUE
        scope_id, raw_amount = args[1], args[2]
    amount = _parse_amount(raw_amount, ctx.out)
    if amount is None:
        return LoopSignal.CONTINUE
    window = BudgetWindow(_DEFAULT_WINDOW)
    if raw_window is not None:
        parsed = _parse_window(raw_window, ctx.out)
        if parsed is None:
            return LoopSignal.CONTINUE
        window = parsed
    warn = _DEFAULT_WARN
    if raw_warn is not None:
        parsed_warn = _parse_amount(raw_warn, ctx.out)
        if parsed_warn is None:
            return LoopSignal.CONTINUE
        warn = parsed_warn
    ledger = ctx.session.ledger
    existing = ledger.budget_policies.find(
        scope_type=scope, scope_id=scope_id, metric="cost_cents", window_kind=window.value
    )
    if existing is not None:
        ledger.budget_policies.set_amount(existing.id, amount)
        ctx.out.line(f"updated {existing.id}: {scope.value} {scope_id} cap -> {amount} cents")
        return LoopSignal.CONTINUE
    policy_id = f"bp_{uuid.uuid4().hex[:12]}"
    ledger.budget_policies.create(
        BudgetPolicy(id=policy_id, scope_type=scope, scope_id=scope_id, amount=amount,
                     warn_percent=warn, window_kind=window.value)
    )
    ctx.out.line(f"set {policy_id}: {scope.value} {scope_id} cap {amount} cents (warn {warn}%, {window.value})")
    return LoopSignal.CONTINUE


def _budget_raise(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) != 2:
        ctx.out.error(f"usage: {_BUDGET_RAISE}")
        return LoopSignal.CONTINUE
    amount = _parse_amount(args[1], ctx.out)
    if amount is None:
        return LoopSignal.CONTINUE
    try:
        _enforcer(ctx).raise_budget_and_resume(
            args[0], amount, now=ctx.session.clock(), decided_by_user_id=_OPERATOR
        )
    except KeyError:
        ctx.out.error(f"no such policy: {args[0]!r}")
        return LoopSignal.CONTINUE
    except ValueError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ctx.out.line(f"raised {args[0]} to {amount} cents and resumed the scope")
    return LoopSignal.CONTINUE


def _budget_dismiss(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) != 1:
        ctx.out.error(f"usage: {_BUDGET_DISMISS}")
        return LoopSignal.CONTINUE
    try:
        _enforcer(ctx).dismiss(args[0], decided_by_user_id=_OPERATOR)
    except KeyError:
        ctx.out.error(f"no such incident: {args[0]!r}")
        return LoopSignal.CONTINUE
    ctx.out.line(f"dismissed {args[0]}; the scope stays paused until 'budget raise'")
    return LoopSignal.CONTINUE


_BUDGET_SET = "budget set <company|employee> [<employee_id>] <cents> [--warn=N] [--window=W]"
_BUDGET_RAISE = "budget raise <policy_id> <cents>"
_BUDGET_DISMISS = "budget dismiss <incident_id>"
_BUDGET = "budget [list | set … | raise … | dismiss …]"

_BUDGET_SUBCOMMANDS = {
    "set": _budget_set,
    "raise": _budget_raise,
    "dismiss": _budget_dismiss,
}


@REGISTRY.command("budget", summary="view or manage budgets -- caps, spend, incidents", usage=_BUDGET)
def _budget(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] == "list":
        return _budget_list(ctx)
    handler = _BUDGET_SUBCOMMANDS.get(ctx.args[0])
    if handler is None:
        ctx.out.error(f"unknown budget subcommand {ctx.args[0]!r}; usage: {_BUDGET}")
        return LoopSignal.CONTINUE
    return handler(ctx, ctx.args[1:])


# -- approvals & governance (spec 04 §5) ------------------------------------------------------------


def _parse_gate(raw: str, out: Console) -> ApprovalGate | None:
    try:
        return ApprovalGate(raw)
    except ValueError:
        choices = ", ".join(gate.value for gate in ApprovalGate)
        out.error(f"unknown gate {raw!r}; choose one of: {choices}")
        return None


def _resolver(ctx: CommandContext) -> GovernanceResolver:
    return GovernanceResolver(ctx.session.ledger)


def _approval_list(ctx: CommandContext) -> LoopSignal:
    pending = ctx.session.ledger.approvals.pending()
    ctx.out.table(
        ("approval", "subject", "id", "gate", "reason"),
        [
            (a.id, a.subject_kind.value, a.subject_id,
             _fmt(a.gate_kind.value if a.gate_kind else None), _preview(a.reason))
            for a in pending
        ],
    )
    return LoopSignal.CONTINUE


def _approval_open(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) < 3:
        ctx.out.error(f"usage: {_APPROVAL_OPEN}")
        return LoopSignal.CONTINUE
    gate = _parse_gate(args[1], ctx.out)
    if gate is None:
        return LoopSignal.CONTINUE
    try:
        approval = _resolver(ctx).open_task_gate(args[0], gate_kind=gate, reason=" ".join(args[2:]))
    except GovernanceError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    except sqlite3.IntegrityError:
        ctx.out.error(f"task {args[0]!r} already has a pending gate")
        return LoopSignal.CONTINUE
    ctx.out.line(f"opened {approval.id}: {gate.value} gate on {args[0]} -- task blocked")
    return LoopSignal.CONTINUE


def _approval_resolve(ctx: CommandContext, args: tuple[str, ...], *, approve: bool) -> LoopSignal:
    usage = _APPROVAL_APPROVE if approve else _APPROVAL_DENY
    if len(args) != 1:
        ctx.out.error(f"usage: {usage}")
        return LoopSignal.CONTINUE
    try:
        outcome = _resolver(ctx).resolve(
            args[0], approve=approve, decided_by_user_id=_OPERATOR, now=ctx.session.clock()
        )
    except GovernanceError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    verb = "approved" if approve else "denied"
    ctx.out.line(
        f"{verb} {outcome.approval_id} -> task {outcome.task_id} is "
        f"{outcome.task_status.value} ({outcome.wakes_fired} wakes)"
    )
    return LoopSignal.CONTINUE


_APPROVAL_OPEN = "approval open <task_id> <acceptance|authorization> <reason…>"
_APPROVAL_APPROVE = "approval approve <approval_id>"
_APPROVAL_DENY = "approval deny <approval_id>"
_APPROVAL = "approval [list | open … | approve <id> | deny <id>]"


@REGISTRY.command("approval", summary="view or resolve approval gates", usage=_APPROVAL)
def _approval(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] == "list":
        return _approval_list(ctx)
    sub = ctx.args[0]
    rest = ctx.args[1:]
    if sub == "open":
        return _approval_open(ctx, rest)
    if sub == "approve":
        return _approval_resolve(ctx, rest, approve=True)
    if sub == "deny":
        return _approval_resolve(ctx, rest, approve=False)
    ctx.out.error(f"unknown approval subcommand {sub!r}; usage: {_APPROVAL}")
    return LoopSignal.CONTINUE


# -- definition of done (spec 04 §1) ----------------------------------------------------------------

_DOD_SET = "dod set <task_id> <command|human_approval|agent_review> [args…]"
_DOD = "dod set …"


def _build_verifier(raw_kind: str, rest: tuple[str, ...], out: Console) -> Verifier | None:
    try:
        kind = DoDKind(raw_kind)
    except ValueError:
        choices = ", ".join(k.value for k in DoDKind)
        out.error(f"unknown DoD kind {raw_kind!r}; choose one of: {choices}")
        return None
    if kind is DoDKind.COMMAND:
        if not rest:
            out.error("a command DoD needs a shell command")
            return None
        return Verifier.command(" ".join(rest))
    if kind is DoDKind.HUMAN_APPROVAL:
        return Verifier.human_approval(approver=rest[0] if rest else "board")
    return Verifier.agent_review(
        reviewer_role=rest[0] if rest else "reviewer", rubric=" ".join(rest[1:])
    )


def _dod_set(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) < 2:
        ctx.out.error(f"usage: {_DOD_SET}")
        return LoopSignal.CONTINUE
    task_id, raw_kind = args[0], args[1]
    if ctx.session.ledger.tasks.get(task_id) is None:
        ctx.out.error(f"no such task: {task_id!r}")
        return LoopSignal.CONTINUE
    verifier = _build_verifier(raw_kind, args[2:], ctx.out)
    if verifier is None:
        return LoopSignal.CONTINUE
    try:
        ctx.session.ledger.dod.create(task_id, verifier)
    except sqlite3.IntegrityError:
        ctx.out.error(f"task {task_id!r} already has a DoD")
        return LoopSignal.CONTINUE
    ctx.out.line(f"set {verifier.kind.value} DoD on {task_id} ({verifier.artifact_class})")
    return LoopSignal.CONTINUE


@REGISTRY.command("dod", summary="set a task's Definition of Done", usage=_DOD)
def _dod(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] != "set":
        ctx.out.error(f"usage: {_DOD}")
        return LoopSignal.CONTINUE
    return _dod_set(ctx, ctx.args[1:])


REGISTRY.alias("?", of="help")
REGISTRY.alias("exit", of="quit")
REGISTRY.alias("budgets", of="budget")
REGISTRY.alias("approvals", of="approval")


__all__ = ["REGISTRY"]
