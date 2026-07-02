"""Routine verbs — the `routine` group and its schedule/concurrency helpers."""

from __future__ import annotations

from chorus.errors import UnknownEmployee
from chorus.facade import Caps, Chorus
from chorus.ledger import (
    RoutineCatchUp,
    RoutineConcurrency,
)
from chorus.observability import LedgerInspector, RoutineView
from chorus.workforce import LedgerWorkforce
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli._render import Console
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _fmt,
    _pop_flag,
    _preview,
    _roles_from_env,
)

_ROUTINE_ADD = (
    'routine add <employee> <intent...> --schedule "<cron>" [--timezone <tz>] '
    "[--concurrency coalesce|skip_if_active|always] [--catch-up skip_missed|backfill_one]"
)
_ROUTINE = "routine add|list|show|pause|resume ... -- recurring work owned by an employee"


def _routine_facade(ctx: CommandContext) -> Chorus:
    """A facade over the session ledger — the routine verbs route through the public API, not internals."""
    ledger = ctx.session.ledger
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=_roles_from_env(),
        caps=Caps(),
    )


def _parse_concurrency(raw: str, out: Console) -> RoutineConcurrency | None:
    try:
        return RoutineConcurrency(raw)
    except ValueError:
        choices = ", ".join(policy.value for policy in RoutineConcurrency)
        out.error(f"unknown concurrency {raw!r}; choose one of: {choices}")
        return None


def _parse_catch_up(raw: str, out: Console) -> RoutineCatchUp | None:
    try:
        return RoutineCatchUp(raw)
    except ValueError:
        choices = ", ".join(policy.value for policy in RoutineCatchUp)
        out.error(f"unknown catch-up {raw!r}; choose one of: {choices}")
        return None


def _next_run(view: RoutineView) -> str:
    """The soonest ``next_run_at`` across a routine's triggers, for the list table."""
    edges = [trigger.next_run_at for trigger in view.triggers if trigger.next_run_at is not None]
    return _fmt(min(edges)) if edges else "-"


def _routine_add(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    raw_schedule, args = _pop_flag(args, "schedule")
    raw_timezone, args = _pop_flag(args, "timezone")
    raw_concurrency, args = _pop_flag(args, "concurrency")
    raw_catch_up, args = _pop_flag(args, "catch-up")
    if raw_schedule is None or len(args) < 2:
        ctx.out.error(f"usage: {_ROUTINE_ADD}")
        return LoopSignal.CONTINUE
    concurrency = RoutineConcurrency.COALESCE
    if raw_concurrency is not None:
        parsed = _parse_concurrency(raw_concurrency, ctx.out)
        if parsed is None:
            return LoopSignal.CONTINUE
        concurrency = parsed
    catch_up = RoutineCatchUp.SKIP_MISSED
    if raw_catch_up is not None:
        parsed_catch = _parse_catch_up(raw_catch_up, ctx.out)
        if parsed_catch is None:
            return LoopSignal.CONTINUE
        catch_up = parsed_catch
    employee, intent = args[0], " ".join(args[1:])
    try:
        view = _routine_facade(ctx).routines.add(
            employee=employee,
            intent_template=intent,
            schedule=raw_schedule,
            concurrency=concurrency,
            catch_up=catch_up,
            timezone=raw_timezone or "UTC",
        )
    except UnknownEmployee as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    except ValueError as exc:
        ctx.out.error(f"bad schedule {raw_schedule!r}: {exc}")
        return LoopSignal.CONTINUE
    ctx.out.line(
        f"routine {view.id}: {view.employee_id} '{intent}' @ {raw_schedule} ({concurrency.value})"
    )
    return LoopSignal.CONTINUE


def _routine_list(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    raw_employee, _ = _pop_flag(args, "employee")
    try:
        views = _routine_facade(ctx).routines.list(employee=raw_employee)
    except UnknownEmployee as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    if not views:
        ctx.out.line("no routines -- 'routine add <employee> <intent> --schedule \"<cron>\"'")
        return LoopSignal.CONTINUE
    ctx.out.table(
        ("routine", "employee", "intent", "status", "concurrency", "next_run"),
        [
            (
                view.id,
                view.employee_id,
                _preview(view.intent_template),
                view.status.value,
                view.concurrency_policy.value,
                _next_run(view),
            )
            for view in views
        ],
    )
    return LoopSignal.CONTINUE


def _routine_show(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if not args:
        ctx.out.error("usage: routine show <routine_id>")
        return LoopSignal.CONTINUE
    try:
        view = _routine_facade(ctx).routines.get(args[0])
    except KeyError:
        ctx.out.error(f"no routine {args[0]!r}")
        return LoopSignal.CONTINUE
    ctx.out.kv(
        {
            "routine": view.id,
            "employee": view.employee_id,
            "intent": view.intent_template,
            "status": view.status.value,
            "concurrency": view.concurrency_policy.value,
            "catch_up": view.catch_up_policy.value,
        }
    )
    if view.triggers:
        ctx.out.table(
            ("trigger", "kind", "cron", "timezone", "next_run", "last_fired"),
            [
                (
                    t.id,
                    t.kind.value,
                    t.cron_expression or "-",
                    t.timezone,
                    _fmt(t.next_run_at),
                    _fmt(t.last_fired_at),
                )
                for t in view.triggers
            ],
        )
    if view.recent_runs:
        ctx.out.table(
            ("run", "status", "task", "coalesced_into"),
            [
                (r.id, r.status.value, _fmt(r.linked_task_id), _fmt(r.coalesced_into_run_id))
                for r in view.recent_runs
            ],
        )
    return LoopSignal.CONTINUE


def _routine_pause(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    return _routine_toggle(ctx, args, verb="pause")


def _routine_resume(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    return _routine_toggle(ctx, args, verb="resume")


def _routine_toggle(ctx: CommandContext, args: tuple[str, ...], *, verb: str) -> LoopSignal:
    if not args:
        ctx.out.error(f"usage: routine {verb} <routine_id>")
        return LoopSignal.CONTINUE
    routine_id = args[0]
    if ctx.session.ledger.routines.get(routine_id) is None:
        ctx.out.error(f"no routine {routine_id!r}")
        return LoopSignal.CONTINUE
    facade = _routine_facade(ctx)
    if verb == "pause":
        facade.routines.pause(routine_id)
        ctx.out.line(f"paused {routine_id}")
    else:
        facade.routines.resume(routine_id)
        ctx.out.line(f"resumed {routine_id}")
    return LoopSignal.CONTINUE


_ROUTINE_SUBCOMMANDS = {
    "add": _routine_add,
    "show": _routine_show,
    "pause": _routine_pause,
    "resume": _routine_resume,
}


@REGISTRY.command(
    "routine", summary="manage recurring work -- cron routines", usage=_ROUTINE, hidden=True
)
def _routine(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] == "list":
        return _routine_list(ctx, ctx.args[1:])
    handler = _ROUTINE_SUBCOMMANDS.get(ctx.args[0])
    if handler is None:
        ctx.out.error(f"unknown routine subcommand {ctx.args[0]!r}; usage: {_ROUTINE}")
        return LoopSignal.CONTINUE
    return handler(ctx, ctx.args[1:])
