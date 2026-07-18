"""Coordination verbs — wakes/message/inbox."""

from __future__ import annotations

from chorus.ids import mint_id
from chorus.ledger import (
    Message,
    MessageKind,
)
from chorus.lifecycle import (
    deliver_message,
)
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _OPERATOR,
    _fmt,
    _preview,
)

_WAKES = "wakes"


@REGISTRY.command("wakes", summary="list queued wakes", usage=_WAKES, hidden=True)
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


@REGISTRY.command(
    "message", summary="deliver a message and wake the recipient", usage=_MESSAGE, hidden=True
)
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
            id=mint_id(),
            to_employee_id=to_employee_id,
            body=body,
            kind=MessageKind.INSTRUCTION,
            from_user_id=_OPERATOR,  # the console operator is the sender (ledger requires exactly one)
        ),
    )
    ctx.out.line(f"delivered to {to_employee_id}; woke {wake.id} ({wake.reason.value})")
    return LoopSignal.CONTINUE


_INBOX = "inbox <employee_id>"


@REGISTRY.command("inbox", summary="show an employee's unread mailbox", usage=_INBOX, hidden=True)
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
