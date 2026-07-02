"""Governance verbs — the `approval` group and its resolver helpers."""

from __future__ import annotations

import sqlite3

from chorus.governance import ApprovalDecision, GovernanceError, GovernanceResolver
from chorus.ledger import (
    ApprovalGate,
)
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli._render import Console
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _OPERATOR,
    _fmt,
    _preview,
)


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
        ("approval", "action", "subject", "id", "gate", "reason"),
        [
            (
                a.id,
                a.action.value,
                a.subject_kind.value,
                a.subject_id,
                _fmt(a.gate_kind.value if a.gate_kind else None),
                _preview(a.reason),
            )
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


_RESOLVE_USAGE: dict[ApprovalDecision, str] = {
    ApprovalDecision.APPROVE: "approval approve <approval_id>",
    ApprovalDecision.DENY: "approval deny <approval_id>",
    ApprovalDecision.REQUEST_REVISION: "approval revise <approval_id>",
}
_RESOLVE_VERB: dict[ApprovalDecision, str] = {
    ApprovalDecision.APPROVE: "approved",
    ApprovalDecision.DENY: "denied",
    ApprovalDecision.REQUEST_REVISION: "revision requested on",
}


def _approval_resolve(
    ctx: CommandContext, args: tuple[str, ...], *, decision: ApprovalDecision
) -> LoopSignal:
    if len(args) != 1:
        ctx.out.error(f"usage: {_RESOLVE_USAGE[decision]}")
        return LoopSignal.CONTINUE
    try:
        outcome = _resolver(ctx).resolve(
            args[0], decision=decision, decided_by_user_id=_OPERATOR, now=ctx.session.clock()
        )
    except GovernanceError as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    ctx.out.line(
        f"{_RESOLVE_VERB[decision]} {outcome.approval_id} -> {outcome.subject_id} is "
        f"{outcome.subject_status} ({outcome.wakes_fired} wakes)"
    )
    return LoopSignal.CONTINUE


_APPROVAL_OPEN = "approval open <task_id> <acceptance|authorization> <reason…>"
_APPROVAL = "approval [list | open … | approve <id> | deny <id> | revise <id>]"

_APPROVAL_DECISIONS: dict[str, ApprovalDecision] = {
    "approve": ApprovalDecision.APPROVE,
    "deny": ApprovalDecision.DENY,
    "revise": ApprovalDecision.REQUEST_REVISION,
}


@REGISTRY.command(
    "approval", summary="view or resolve approval gates", usage=_APPROVAL, hidden=True
)
def _approval(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] == "list":
        return _approval_list(ctx)
    sub = ctx.args[0]
    rest = ctx.args[1:]
    if sub == "open":
        return _approval_open(ctx, rest)
    decision = _APPROVAL_DECISIONS.get(sub)
    if decision is not None:
        return _approval_resolve(ctx, rest, decision=decision)
    ctx.out.error(f"unknown approval subcommand {sub!r}; usage: {_APPROVAL}")
    return LoopSignal.CONTINUE


# -- definition of done (spec 04 §1) ----------------------------------------------------------------
