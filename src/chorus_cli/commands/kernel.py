"""Kernel verbs — tick/chat + cost/schema read-outs."""

from __future__ import annotations

from chorus.workforce import EmployeeStatus
from chorus_cli._chat import ChatRenderBus, run_chat
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _fmt,
)

_TICK = "tick"


@REGISTRY.command(
    "tick",
    summary="run one kernel pulse -- dispatch a real beat (needs Azure keys)",
    usage=_TICK,
    hidden=True,
)
def _tick(ctx: CommandContext) -> LoopSignal:
    if ctx.args:
        ctx.out.error(f"usage: {_TICK}")
        return LoopSignal.CONTINUE
    if ctx.session.minimal_mode:
        ctx.out.line(
            "heartbeat is already live -- use 'check ledger' or 'check employee' to watch it land"
        )
        return LoopSignal.CONTINUE
    beats = ctx.session.beats
    if beats is None:
        ctx.out.error(
            "no beat runner configured -- set AZURE_OPENAI_API_KEY, AZURE_OPENAI_BASE_URL, "
            "AZURE_OPENAI_DEPLOYMENT and relaunch"
        )
        return LoopSignal.CONTINUE
    ctx.out.line(
        f"ticking the kernel (model {beats.model}) -- this runs a real beat, please wait..."
    )
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
    "chat",
    summary="converse with an employee -- each line runs a real beat (needs Azure keys)",
    usage=_CHAT,
    hidden=True,
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
        ctx.out.line(
            f"note: {employee_id} is paused -- its turns will be gated until you 'resume' it"
        )
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


@REGISTRY.command("cost", summary="show an employee's recorded spend", usage=_COST, hidden=True)
def _cost(ctx: CommandContext) -> LoopSignal:
    if len(ctx.args) != 1:
        ctx.out.error(f"usage: {_COST}")
        return LoopSignal.CONTINUE
    spent = ctx.session.ledger.cost_events.spent_cents(ctx.args[0])
    ctx.out.line(f"{ctx.args[0]} has spent {spent} cents")
    return LoopSignal.CONTINUE


_SCHEMA = "schema"


@REGISTRY.command("schema", summary="show the ledger schema version", usage=_SCHEMA, hidden=True)
def _schema(ctx: CommandContext) -> LoopSignal:
    ctx.out.line(f"schema version: {_fmt(ctx.session.ledger.schema_version())}")
    return LoopSignal.CONTINUE


# -- budgets (spec 04 §3) ---------------------------------------------------------------------------
