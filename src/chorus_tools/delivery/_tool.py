"""`ExecuteGoLiveTool` — turn an APPROVED go-live gate into actual reach (design doc: the tool).

The executor half of the §05 dark node: `stage_go_live` opened the gate; once a human approves it,
Mira calls this to publish the staged draft. Fail-closed at every step — no beat context, no gate,
a pending or denied gate, a gate for another task, or nothing staged: all rejected, nothing ships.
Idempotent per approval: a re-call returns the standing delivery instead of publishing twice. The
model never names WHAT to publish — only the standing staged draft for this task is publishable.
"""

from __future__ import annotations

from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.ledger import Approval, ApprovalAction, ApprovalStatus, Ledger
from chorus_tools._beat import task_id_or_none
from chorus_tools._go_live import GoLiveAction
from chorus_tools.cms import ContentType, DraftRef
from chorus_tools.cms._index import CmsDraftIndex
from chorus_tools.delivery._index import DeliveryIndex
from chorus_tools.delivery._types import DeliveryError, DeliveryRecord
from chorus_tools.delivery.email import EmailDelivery
from chorus_tools.delivery.publish import PublishBackend

# Worktree locations (beside the beat context the kernel writes).
_DRAFTS_RELATIVE = Path(".harness") / "cms-drafts.json"
_DELIVERIES_RELATIVE = Path(".harness") / "deliveries.json"


class ExecuteGoLiveInput(BaseModel):
    """Typed contract for ``execute_go_live`` — validated before anything is looked up."""

    content_type: ContentType = Field(
        description="which staged draft to publish: blog | social | email"
    )
    approval_id: str | None = Field(
        default=None,
        description="optional: the specific gate to execute; omitted = this task's latest gate",
    )


class ExecuteGoLiveTool(BaseTool):
    """Execute an approved go-live: publish the staged draft, exactly once per approval."""

    name = "execute_go_live"
    description = (
        "Execute an APPROVED go-live: publish this task's staged CMS draft so it goes LIVE. "
        "Call this ONLY after stage_go_live was approved by a human — if the gate is still "
        "pending or was denied, this tool refuses and you must stop. Args: content_type "
        "(blog|social|email); approval_id optional (defaults to this task's latest gate). "
        "Idempotent: re-calling returns the existing delivery, it never publishes twice."
    )
    # tier_required=1 (REPO_WRITE): the write effect is gated; the human approval is the authority.
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = ExecuteGoLiveInput

    def __init__(
        self,
        ledger: Ledger,
        backend: PublishBackend,
        email_delivery: EmailDelivery | None = None,
    ) -> None:
        self._ledger = ledger
        self._backend = backend
        self._email_delivery = email_delivery

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = ExecuteGoLiveInput.model_validate(input)
        except ValidationError as exc:
            return _rejected(str(exc))

        task_id = task_id_or_none(ctx.working_dir)
        if task_id is None:
            return _rejected("no beat context — execute_go_live only runs inside a task beat")

        deliveries = DeliveryIndex(ctx.working_dir / _DELIVERIES_RELATIVE)
        gate = self._resolve_gate(task_id, args.approval_id, deliveries)
        if gate is None:
            return _rejected(
                "no go-live gate exists for this task — run stage_go_live first, then wait for approval"
            )
        if gate.status is ApprovalStatus.PENDING:
            return _rejected(
                f"gate {gate.id} is still PENDING human approval — do not publish; stop and wait"
            )
        if gate.status is not ApprovalStatus.APPROVED:
            return _rejected(
                f"gate {gate.id} was {gate.status.value} (denied) — the reach must NOT be executed"
            )

        standing = deliveries.standing_delivery(gate.id)
        if standing is not None:
            return _delivered(standing, already=True)

        draft = self._standing_draft(ctx.working_dir, args.content_type, task_id)
        if draft is None:
            return _rejected(
                f"nothing staged to publish for content_type={args.content_type.value!r} — "
                "run cms_draft first"
            )

        # The reach per channel: email GOES OUT (send), everything else GOES UP (publish). A publish
        # is an idempotent Strapi flip; a send is at-most-once, so it carries the gate id as an
        # idempotency key so a retry can never double-send.
        if args.content_type is ContentType.EMAIL:
            if self._email_delivery is None:
                return _rejected(
                    "email delivery is not configured on this harness — the send cannot execute"
                )
            action = GoLiveAction.SEND
        else:
            action = GoLiveAction.PUBLISH

        try:
            if self._email_delivery is not None and action is GoLiveAction.SEND:
                landed = self._email_delivery.send(draft, idempotency_key=gate.id)
            else:
                landed = self._backend.publish(draft)
        except DeliveryError as exc:
            return _failed(str(exc), action=action)

        record = DeliveryRecord(
            approval_id=gate.id,
            action=action,
            target=args.content_type.value,
            published=landed,
        )
        deliveries.record(record)
        return _delivered(record, already=False)

    def _resolve_gate(
        self, task_id: str, approval_id: str | None, deliveries: DeliveryIndex
    ) -> Approval | None:
        """The gate this beat may execute — explicit id (must belong to THIS task) or resolved.

        An APPROVED gate still awaiting its delivery outranks any newer duplicate (an accidental
        re-stage, pending or human-denied) — the authorised reach must execute regardless of the
        noise staged after it. With no such gate, the newest gate speaks for the task's state
        (pending → wait · denied → dead · delivered → idempotent return upstream).
        """
        if approval_id is not None:
            gate = self._ledger.approvals.get(approval_id)
            if gate is None or gate.subject_id != task_id:
                return None  # unknown, or someone else's gate — never executable from this beat
            return gate
        gates = [
            gate
            for gate in self._ledger.approvals.for_subject(task_id)
            if gate.action is ApprovalAction.TASK_GATE
        ]
        for gate in gates:  # newest first
            if (
                gate.status is ApprovalStatus.APPROVED
                and deliveries.standing_delivery(gate.id) is None
            ):
                return gate
        return gates[0] if gates else None

    def _standing_draft(
        self, working_dir: Path, content_type: ContentType, task_id: str
    ) -> DraftRef | None:
        index = CmsDraftIndex(working_dir / _DRAFTS_RELATIVE)
        return index.standing_ref(f"{content_type.value}:{task_id}")


def _delivered(record: DeliveryRecord, *, already: bool) -> ToolResult:
    verb = "already delivered" if already else "delivered"
    return ToolResult(
        content=(
            "status: delivered\n"
            f"summary: go-live {verb} — {record.target} is LIVE at {record.published.url}\n"
            "next_actions: the reach is executed; do not publish again — finish the beat\n"
            f"artifacts: {record.as_dict()}"
        ),
        is_error=False,
        metadata={
            "status": "delivered",
            "already_delivered": already,
            "delivery": record.as_dict(),
        },
    )


def _rejected(detail: str) -> ToolResult:
    return ToolResult(
        content=(
            "status: error\n"
            f"summary: go-live NOT executed — {detail}\n"
            "root_cause: the gate check failed — only an APPROVED gate for THIS task can execute\n"
            "safe_retry: if the gate is pending, stop and wait for the human; if nothing is staged, "
            "cms_draft then stage_go_live first\n"
            "stop_condition: never attempt to publish around the gate; nothing was shipped"
        ),
        is_error=True,
    )


def _failed(detail: str, *, action: GoLiveAction) -> ToolResult:
    # A publish is an idempotent flip (safe to retry). A send is at-most-once and leaves NO delivery
    # record until it succeeds, so the transport may already have accepted the message before the
    # failure — a blind retry risks a double-send. The two need different recovery guidance.
    if action is GoLiveAction.SEND:
        return ToolResult(
            content=(
                "status: error\n"
                f"summary: the email transport failed — {detail}\n"
                "root_cause: the ESP rejected or could not confirm the send (auth, network, address)\n"
                "safe_retry: do NOT simply resend — the message may ALREADY have been delivered "
                "(the transport can accept then fail before confirming). Verify in the ESP whether "
                "it went out before any retry\n"
                "stop_condition: if delivery is unconfirmed, stop and report — a blind retry can "
                "double-send; the approval stays valid for a confirmed single send"
            ),
            is_error=True,
        )
    return ToolResult(
        content=(
            "status: error\n"
            f"summary: the publish backend failed — {detail}\n"
            "root_cause: the CMS rejected or could not complete the publish (auth, network, target)\n"
            "safe_retry: publishing is idempotent — verify the CMS is reachable, then retry once; "
            "the gate stays approved\n"
            "stop_condition: if it fails again, stop — the CMS is unavailable, not the approval"
        ),
        is_error=True,
    )


__all__ = ["ExecuteGoLiveInput", "ExecuteGoLiveTool"]
