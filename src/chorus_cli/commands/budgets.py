"""Budget verbs — the `budget` group and its policy/incident helpers."""

from __future__ import annotations

from chorus.budgets import BudgetEnforcer, BudgetWindow, window_start
from chorus.ids import mint_id
from chorus.ledger import (
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
)
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli._render import Console
from chorus_cli.commands._base import REGISTRY
from chorus_cli.commands._shared import (
    _OPERATOR,
    _fmt,
    _pop_flag,
)

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
        ctx.out.line(
            "no budgets -- 'budget set employee <id> <cents>' or 'budget set company <cents>'"
        )
        return LoopSignal.CONTINUE
    rows = []
    for policy in policies:
        spent = _spent_for(ctx, policy)
        pct = f"{spent * 100 // policy.amount}%" if policy.amount else "-"
        rows.append(
            (
                policy.id,
                policy.scope_type.value,
                policy.scope_id,
                policy.amount,
                spent,
                pct,
                policy.window_kind,
                _budget_status(ctx, policy, spent),
            )
        )
    ctx.out.table(
        ("policy", "scope", "id", "cap_cents", "spent_cents", "used", "window", "status"), rows
    )
    incidents = [i for p in policies for i in ledger.budget_incidents.open_for_policy(p.id)]
    if incidents:
        ctx.out.line("open incidents:")
        ctx.out.table(
            ("incident", "policy", "threshold", "observed_cents", "approval"),
            [
                (i.id, i.policy_id, i.threshold_type.value, i.amount_observed, _fmt(i.approval_id))
                for i in incidents
            ],
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
    policy_id = mint_id()
    ledger.budget_policies.create(
        BudgetPolicy(
            id=policy_id,
            scope_type=scope,
            scope_id=scope_id,
            amount=amount,
            warn_percent=warn,
            window_kind=window.value,
        )
    )
    ctx.out.line(
        f"set {policy_id}: {scope.value} {scope_id} cap {amount} cents (warn {warn}%, {window.value})"
    )
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


@REGISTRY.command(
    "budget", summary="view or manage budgets -- caps, spend, incidents", usage=_BUDGET, hidden=True
)
def _budget(ctx: CommandContext) -> LoopSignal:
    if not ctx.args or ctx.args[0] == "list":
        return _budget_list(ctx)
    handler = _BUDGET_SUBCOMMANDS.get(ctx.args[0])
    if handler is None:
        ctx.out.error(f"unknown budget subcommand {ctx.args[0]!r}; usage: {_BUDGET}")
        return LoopSignal.CONTINUE
    return handler(ctx, ctx.args[1:])


# -- approvals & governance (spec 04 §5) ------------------------------------------------------------
