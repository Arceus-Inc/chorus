"""The marketer's ``stage_go_live`` capability, exposed to the model as a dream tool (§07/§11).

Reach that touches the world — **publish** to an owned channel, **send** to an audience, **spend** ad
budget (§11 blast radii) — is an explicit typed micro-tool whose *call* opens a human approval gate;
it never executes the effect. This is a thin dream envelope that **composes governance's public**
:meth:`~chorus.governance.GovernanceResolver.open_task_gate` — the same way :class:`DecomposeTool`
composes :class:`~chorus.lifecycle.CapabilityService`. Core chorus is untouched; the typed request is
the tool's input contract, nothing more. Fail-closed: a bad request stages nothing; a valid one stages
and gates, returning the observation contract (status / summary / next_actions / artifacts).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError, model_validator

from chorus.governance import GovernanceError, GovernanceResolver
from chorus.heartbeat import BeatContext
from chorus.ledger import ApprovalAction, ApprovalGate, ApprovalStatus, SqliteLedger


class GoLiveAction(StrEnum):
    """The irreversible reach a marketer stages for approval (design doc §11 blast radii)."""

    PUBLISH = "publish"  # push to an owned channel (blog, site, social)
    SEND = "send"  # deliver to an audience (email / lifecycle)
    SPEND = "spend"  # commit ad budget


class GoLiveInput(BaseModel):
    """Typed contract for ``stage_go_live`` — validated before any gate is opened."""

    action: GoLiveAction = Field(
        description="the reach: publish (owned channel), send (audience), or spend (ad budget)"
    )
    target: str = Field(min_length=1, description="the channel, audience, or ad platform the reach lands on")
    content_ref: str = Field(min_length=1, description="the staged deliverable to go live, e.g. 'content_draft.md'")
    amount_cents: int | None = Field(
        default=None, description="budget in cents; REQUIRED for a spend, omitted otherwise"
    )

    @model_validator(mode="after")
    def _amount_matches_action(self) -> GoLiveInput:
        if self.action is GoLiveAction.SPEND:
            if self.amount_cents is None or self.amount_cents <= 0:
                raise ValueError("a spend go-live requires a positive amount_cents")
        elif self.amount_cents is not None:
            raise ValueError(f"amount_cents is only valid for a spend, not a {self.action.value}")
        return self

    @property
    def reason(self) -> str:
        """The human-readable gate reason an approver reads."""
        money = f" ${self.amount_cents / 100:.2f}" if self.amount_cents is not None else ""
        return f"go-live {self.action.value}{money} to {self.target} ({self.content_ref})"


class GoLiveTool(BaseTool):
    """Stage an irreversible go-live for human approval — never execute it (fail-closed)."""

    name = "stage_go_live"
    description = (
        "Stage an irreversible go-live — publish to an owned channel, send to an audience, or spend "
        "ad budget — for HUMAN APPROVAL. This does NOT execute: it stages the action and opens an "
        "approval gate; reach happens only after a human approves. Draft and self-review first; call "
        "this only when the deliverable is final. Args: action (publish|send|spend), target, "
        "content_ref (the staged file), and amount_cents (only for a spend)."
    )
    # tier_required=1 (REPO_WRITE): a mutating tool is gated as a write effect (mirrors DecomposeTool).
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = GoLiveInput

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = GoLiveInput.model_validate(input)
        except ValidationError as exc:
            return _rejected(str(exc))

        beat = BeatContext.read(ctx.working_dir)
        # Re-stage guard: an APPROVED gate still awaiting its delivery means the reach is already
        # authorised — a second gate would fork the authority. The right verb from here is
        # execute_go_live; this rejection is what steers a confused model back onto it.
        awaiting = self._approved_awaiting_execution(beat.task_id, ctx.working_dir)
        if awaiting is not None:
            return _rejected(
                f"gate {awaiting} is already APPROVED and awaiting execution — do NOT stage again; "
                "call execute_go_live to publish it"
            )
        # Idempotent per beat: a task carries at most one pending gate (the exact-once approval index),
        # so a re-stage returns the standing gate rather than colliding on the unique index.
        standing = self._pending_task_gate(beat.task_id)
        try:
            gate_id = (
                standing
                if standing is not None
                else GovernanceResolver(self._ledger)
                .open_task_gate(beat.task_id, gate_kind=ApprovalGate.AUTHORIZATION, reason=args.reason)
                .id
            )
        except GovernanceError as exc:
            return _rejected(str(exc))
        return _gated(args, gate_id)

    def _pending_task_gate(self, task_id: str) -> str | None:
        for approval in self._ledger.approvals.pending():
            if approval.subject_id == task_id and approval.action is ApprovalAction.TASK_GATE:
                return approval.id
        return None

    def _approved_awaiting_execution(self, task_id: str, working_dir: Path) -> str | None:
        """The id of an APPROVED gate whose delivery has not landed yet, if any."""
        # Local import: the delivery package imports GoLiveAction from this module, so the reverse
        # dependency stays out of module scope to avoid an import cycle.
        from chorus_tools.delivery._index import DeliveryIndex

        deliveries = DeliveryIndex(working_dir / ".harness" / "deliveries.json")
        for approval in self._ledger.approvals.for_subject(task_id):
            if (
                approval.action is ApprovalAction.TASK_GATE
                and approval.status is ApprovalStatus.APPROVED
                and deliveries.standing_delivery(approval.id) is None
            ):
                return approval.id
        return None


def _gated(args: GoLiveInput, gate_id: str) -> ToolResult:
    return ToolResult(
        content=(
            "status: gated\n"
            f"summary: {args.action.value} to {args.target} STAGED — not sent; approval {gate_id} opened\n"
            f"next_actions: a human approves {gate_id} to execute the go-live, or denies to discard\n"
            f"artifacts: gate={gate_id} content_ref={args.content_ref}"
        ),
        is_error=False,
        metadata={
            "status": "gated",
            "gate_id": gate_id,
            "action": args.action.value,
            "next_actions": [f"approve {gate_id}", f"deny {gate_id}"],
            "artifacts": {"gate": gate_id, "content_ref": args.content_ref},
        },
    )


def _rejected(detail: str) -> ToolResult:
    return ToolResult(
        content=(
            "status: error\n"
            f"summary: go-live not staged — {detail}\n"
            "root_cause: the request failed the stage_go_live schema\n"
            "safe_retry: re-issue with action in {publish,send,spend}, a non-empty target and "
            "content_ref, and amount_cents only for a spend\n"
            "stop_condition: do not retry the same payload; nothing was staged"
        ),
        is_error=True,
    )


__all__ = ["GoLiveAction", "GoLiveInput", "GoLiveTool"]
