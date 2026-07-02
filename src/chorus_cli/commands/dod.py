"""DoD verbs — the `dod` group (set/revise) and its verifier builder."""

from __future__ import annotations

from chorus.lifecycle import (
    NoRevision,
    RevisionAuthorityError,
    revise_dod,
)
from chorus.outcomes import DoDKind, Verifier
from chorus_cli._context import CommandContext, LoopSignal
from chorus_cli._render import Console
from chorus_cli.commands._base import REGISTRY

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
    if ctx.session.ledger.dod.get_for_task(task_id) is not None:
        # Explicit pre-check for the friendly duplicate message, rather than catching a low-level
        # sqlite3.IntegrityError (which would also mask any *other* integrity fault). This is an
        # interactive single-console verb, so the LBYL check has no meaningful race.
        ctx.out.error(f"task {task_id!r} already has a DoD")
        return LoopSignal.CONTINUE
    verifier = _build_verifier(raw_kind, args[2:], ctx.out)
    if verifier is None:
        return LoopSignal.CONTINUE
    ctx.session.ledger.dod.create(task_id, verifier)
    ctx.out.line(f"set {verifier.kind.value} DoD on {task_id} ({verifier.artifact_class})")
    return LoopSignal.CONTINUE


_DOD_REVISE = "dod revise <task_id> <manager_id> <command|human_approval|agent_review> [args…]"


def _dod_revise(ctx: CommandContext, args: tuple[str, ...]) -> LoopSignal:
    if len(args) < 3:
        ctx.out.error(f"usage: {_DOD_REVISE}")
        return LoopSignal.CONTINUE
    task_id, revised_by = args[0], args[1]
    verifier = _build_verifier(args[2], args[3:], ctx.out)
    if verifier is None:
        return LoopSignal.CONTINUE
    try:
        outcome = revise_dod(
            ctx.session.ledger, task_id=task_id, new_verifier=verifier, revised_by=revised_by
        )
    except (RevisionAuthorityError, NoRevision) as exc:
        ctx.out.error(str(exc))
        return LoopSignal.CONTINUE
    if outcome.applied:
        ctx.out.line(f"tightened {task_id}'s DoD -> {verifier.kind.value} (applied now)")
    else:
        ctx.out.line(
            f"loosen staged on {task_id} -> opened gate {outcome.approval_id} "
            "(resolve with `approval approve|deny|revise`)"
        )
    return LoopSignal.CONTINUE


@REGISTRY.command(
    "dod", summary="set or revise a task's Definition of Done", usage=_DOD, hidden=True
)
def _dod(ctx: CommandContext) -> LoopSignal:
    if ctx.args and ctx.args[0] == "set":
        return _dod_set(ctx, ctx.args[1:])
    if ctx.args and ctx.args[0] == "revise":
        return _dod_revise(ctx, ctx.args[1:])
    ctx.out.error(f"usage: {_DOD}")
    return LoopSignal.CONTINUE


# -- routines (recurring work, spec 13 §7) ----------------------------------------------------------
