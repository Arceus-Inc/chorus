"""The CEO employee's governance tools — the reverse edge of the strategy seam.

Every other employee's tools live here in ``chorus_tools`` and bind to a data backend the composition
root injects (the manager's ledger, the analyst's warehouse). The CEO is no exception: these tools bind
to a :class:`dream.contracts.GovernancePort`, and the composition root wires that port to horizon's
control plane. Chorus never imports horizon — it only ever sees the Port. The employee reads the
direction and steers it (approve / reject a proposal, reprioritise or archive a goal); horizon decides
what those verbs actually do to its tree.
"""

from __future__ import annotations

from dream.contracts import GovernancePort, GovernanceView
from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus.heartbeat import BeatContext

# The worktree audit trail every governance WRITE appends to. It is the artifact-side proof that the
# CEO's state-changing actions actually happened: approve/reject/reprioritise/archive mutate horizon's
# tree (invisible in the worktree), so without this a read-only reviewer re-reading the files cannot
# confirm the work and wrongly blocks the beat. The directive cites it; the reviewer reads it.
_LEDGER_FILE = "governance-ledger.md"


def _audit(ctx: ToolExecutionContext, line: str) -> None:
    """Append one run-stamped line to the worktree's governance ledger (best-effort).

    A standing worktree accumulates lines across beats, so each line carries its beat's
    run id — dream's per-beat task identity IS the chorus run_id, which is what lets an
    evaluator separate THIS beat's actions from prior beats' without guessing.
    """
    try:
        path = ctx.working_dir / _LEDGER_FILE
        try:
            stamp = f"[run {BeatContext.read(ctx.working_dir).run_id}] "
        except Exception:  # no beat context (e.g. a bare test harness) — log unstamped
            stamp = ""
        header = (
            "" if path.exists() else "# Governance ledger — one run-stamped line per action\n\n"
        )
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{header}- {stamp}{line}\n")
    except Exception:  # an audit-log hiccup must never break the actual governance action
        pass


def _render(view: GovernanceView) -> str:
    """A plain-text digest of the direction — decisions with their goals, then open proposals.

    Deliberately terse and unadorned: the CEO model is a reasoning model behind a content filter, and
    a compact factual render (ids, titles, numbers) never trips it the way a florid one can.
    """
    lines: list[str] = []
    if view.decisions:
        lines.append("DECISIONS")
        for d in view.decisions:
            lines.append(f"- [{d.decision_id}] ({d.status}) {d.statement}")
            for g in d.goals:
                tail = f" metric={g.metric} target={g.target}" if g.metric else ""
                lines.append(
                    f"    - [{g.goal_id}] {g.title} — priority={g.priority} "
                    f"health={g.health} status={g.status} score={g.score:.2f}{tail}"
                )
    else:
        lines.append("DECISIONS: none")
    lines.append("")
    if view.proposals:
        lines.append("OPEN PROPOSALS")
        for p in view.proposals:
            conf = "n/a" if p.confidence is None else f"{p.confidence:.2f}"
            lines.append(
                f"- [{p.proposal_id}] ({p.status}) {p.statement} "
                f"— confidence={conf} evidence={p.evidence}"
            )
    else:
        lines.append("OPEN PROPOSALS: none")
    # The decided proposals — the record of adjudication already done (this beat's approvals/rejections
    # land here the moment they happen). Shown so a directive can cite them and a reviewer can confirm
    # the work; an empty OPEN list plus these is proof the queue was worked, not that nothing was there.
    if view.decided:
        lines.append("")
        lines.append("RECENTLY DECIDED PROPOSALS")
        for p in view.decided:
            lines.append(f"- [{p.proposal_id}] ({p.status}) {p.statement}")
    return "\n".join(lines)


class GovernanceReadInput(BaseModel):
    """``governance_read`` takes no arguments — it always reads the whole direction."""


class GovernanceReadTool(BaseTool):
    """Read the company's current direction — decisions, their goals, and open proposals."""

    name = "governance_read"
    description = (
        "Read the company's current direction: the standing decisions with their goals (priority, "
        "health, status, score) and every open proposal awaiting a call. Use this first, before "
        "approving, rejecting, reprioritising, or archiving anything."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=30.0)
    input_model = GovernanceReadInput

    def __init__(self, port: GovernancePort) -> None:
        self._port = port

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        view = self._port.read_direction()
        return ToolResult(
            content=_render(view),
            structured={
                "decisions": len(view.decisions),
                "proposals": len(view.proposals),
                "decided": len(view.decided),
            },
        )


class ProposalApproveInput(BaseModel):
    """Arguments for ``proposal_approve`` — accept one open proposal into the direction."""

    proposal_id: str = Field(
        description="the open proposal's id (prop_…), as shown by governance_read"
    )


class ProposalApproveTool(BaseTool):
    """Approve one open proposal — promote it into the company's standing direction."""

    name = "proposal_approve"
    description = (
        "Approve one open proposal by id, promoting it into the company's standing direction. Only "
        "approve a proposal you have read and judged sound; the id must be one governance_read listed."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = ProposalApproveInput

    def __init__(self, port: GovernancePort) -> None:
        self._port = port

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        args = ProposalApproveInput.model_validate(input)
        beat = BeatContext.read(ctx.working_dir)
        try:
            decision_id = self._port.approve_proposal(args.proposal_id, by=beat.employee_id)
        except Exception as exc:  # the port (horizon) rejects a stale/unknown/duplicate id
            return ToolResult(
                content=(
                    f"refused: could not approve {args.proposal_id} — {exc}. Call governance_read "
                    "again for the current open proposal ids; it may already be decided."
                ),
                structured={"proposal_id": args.proposal_id, "error": str(exc)},
                is_error=True,
            )
        _audit(
            ctx,
            f"APPROVED proposal {args.proposal_id} → decision {decision_id} (by {beat.employee_id})",
        )
        return ToolResult(
            content=f"approved proposal {args.proposal_id} — it is now decision {decision_id}",
            structured={"proposal_id": args.proposal_id, "decision_id": decision_id},
        )


class ProposalRejectInput(BaseModel):
    """Arguments for ``proposal_reject`` — decline one open proposal."""

    proposal_id: str = Field(
        description="the open proposal's id (prop_…), as shown by governance_read"
    )
    reason: str = Field(
        default="", description="a short reason for the record — why this proposal was declined"
    )


class ProposalRejectTool(BaseTool):
    """Reject one open proposal — decline it, with a reason for the record."""

    name = "proposal_reject"
    description = (
        "Reject one open proposal by id, declining it. Give a short reason for the record. Use this "
        "for proposals that are weak, off-strategy, or premature; the id must be one governance_read "
        "listed."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = ProposalRejectInput

    def __init__(self, port: GovernancePort) -> None:
        self._port = port

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        args = ProposalRejectInput.model_validate(input)
        beat = BeatContext.read(ctx.working_dir)
        try:
            self._port.reject_proposal(args.proposal_id, by=beat.employee_id, reason=args.reason)
        except Exception as exc:  # the port (horizon) rejects a stale/unknown id
            return ToolResult(
                content=(
                    f"refused: could not reject {args.proposal_id} — {exc}. Call governance_read "
                    "again for the current open proposal ids; it may already be decided."
                ),
                structured={"proposal_id": args.proposal_id, "error": str(exc)},
                is_error=True,
            )
        _audit(
            ctx,
            f"REJECTED proposal {args.proposal_id} (by {beat.employee_id}) — reason: {args.reason or 'n/a'}",
        )
        return ToolResult(
            content=f"rejected proposal {args.proposal_id}",
            structured={"proposal_id": args.proposal_id, "reason": args.reason},
        )


class GoalSetPriorityInput(BaseModel):
    """Arguments for ``goal_set_priority`` — reprioritise one goal."""

    goal_id: str = Field(
        description=(
            "the goal's id (goal_…), as shown by governance_read — not a decision (dec_…) "
            "or proposal (prop_…) id"
        )
    )
    priority: str = Field(description="the new priority: one of low, medium, high")


# The company's coarse priority vocabulary is low / medium / high. Common CEO synonyms are mapped to
# the nearest band so a natural word ("critical", "urgent") steers the goal instead of erroring.
_PRIORITY_ALIASES: dict[str, str] = {
    "low": "low",
    "backlog": "low",
    "none": "low",
    "medium": "medium",
    "med": "medium",
    "normal": "medium",
    "moderate": "medium",
    "high": "high",
    "highest": "high",
    "critical": "high",
    "urgent": "high",
    "top": "high",
    "p0": "high",
    "p1": "high",
}


class GoalSetPriorityTool(BaseTool):
    """Set one goal's priority — steer where the company's effort concentrates."""

    name = "goal_set_priority"
    description = (
        "Set one goal's priority by id. The company's bands are low, medium, high (a synonym like "
        "'critical' or 'urgent' maps to high). This steers where the company concentrates effort; the "
        "id must be one governance_read listed."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = GoalSetPriorityInput

    def __init__(self, port: GovernancePort) -> None:
        self._port = port

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        args = GoalSetPriorityInput.model_validate(input)
        band = _PRIORITY_ALIASES.get(args.priority.strip().lower())
        if band is None:
            return ToolResult(
                content=(
                    f"refused: unknown priority {args.priority!r}. Use one of low, medium, high "
                    "(a word like 'critical' maps to high)."
                ),
                structured={"goal_id": args.goal_id, "priority": args.priority},
                is_error=True,
            )
        try:
            applied = self._port.set_priority(args.goal_id, band)
        except Exception as exc:  # the port (horizon) rejects an unknown/stale goal id
            return ToolResult(
                content=(
                    f"refused: could not set priority on {args.goal_id} — {exc}. Call governance_read "
                    "again for the current goal ids."
                ),
                structured={"goal_id": args.goal_id, "error": str(exc)},
                is_error=True,
            )
        _audit(ctx, f"SET PRIORITY goal {args.goal_id} → {applied}")
        return ToolResult(
            content=f"set goal {args.goal_id} priority to {applied}",
            structured={"goal_id": args.goal_id, "priority": applied},
        )


class GoalArchiveInput(BaseModel):
    """Arguments for ``goal_archive`` — retire one goal from the active direction."""

    goal_id: str = Field(
        description=(
            "the goal's id (goal_…), as shown by governance_read — not a decision (dec_…) "
            "or proposal (prop_…) id"
        )
    )


class GoalArchiveTool(BaseTool):
    """Archive one goal — retire it from the active direction."""

    name = "goal_archive"
    description = (
        "Archive one goal by id, retiring it from the active direction. Use this for goals that are "
        "done, obsolete, or superseded; the id must be one governance_read listed."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = GoalArchiveInput

    def __init__(self, port: GovernancePort) -> None:
        self._port = port

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        args = GoalArchiveInput.model_validate(input)
        try:
            self._port.archive_goal(args.goal_id)
        except Exception as exc:  # the port (horizon) rejects an unknown/stale goal id
            return ToolResult(
                content=(
                    f"refused: could not archive {args.goal_id} — {exc}. Call governance_read again "
                    "for the current goal ids."
                ),
                structured={"goal_id": args.goal_id, "error": str(exc)},
                is_error=True,
            )
        _audit(ctx, f"ARCHIVED goal {args.goal_id}")
        return ToolResult(
            content=f"archived goal {args.goal_id}",
            structured={"goal_id": args.goal_id},
        )


GOVERNANCE_TOOL_NAMES: frozenset[str] = frozenset(
    {"governance_read", "proposal_approve", "proposal_reject", "goal_set_priority", "goal_archive"}
)


def governance_tool(name: str, port: GovernancePort) -> BaseTool | None:
    """Map a capability name → its governance ``BaseTool`` bound to ``port`` (else ``None``).

    The composition-root analogue of ``_capability_tool`` for the governance seam: the factory calls
    this for each of a role's declared tools when a :class:`GovernancePort` is present.
    """
    if name == "governance_read":
        return GovernanceReadTool(port)
    if name == "proposal_approve":
        return ProposalApproveTool(port)
    if name == "proposal_reject":
        return ProposalRejectTool(port)
    if name == "goal_set_priority":
        return GoalSetPriorityTool(port)
    if name == "goal_archive":
        return GoalArchiveTool(port)
    return None


__all__ = [
    "GOVERNANCE_TOOL_NAMES",
    "GoalArchiveTool",
    "GoalSetPriorityTool",
    "GovernanceReadTool",
    "ProposalApproveTool",
    "ProposalRejectTool",
    "governance_tool",
]
