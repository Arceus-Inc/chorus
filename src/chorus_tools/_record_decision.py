"""The PM ``record_decision`` capability, exposed to the model as a dream tool (pm design doc §10).

This is the composition seam that makes the Decision OS model-callable: the PM calls ``record_decision``
mid-beat and chorus writes an immutable :class:`~chorus.ledger.DecisionRecord` + its cited
:class:`~chorus.ledger.Claim` rows. The tool is a thin dream envelope over
:class:`~chorus.lifecycle.CapabilityService` — it validates the input (pydantic), **enforces the
confidence floor** (a floor-failing decision is refused with a recovery hint, never written), reads the
per-beat :class:`~chorus.heartbeat.BeatContext` for its task + revision, delegates the atomic write, and
mirrors ``decision.json`` into the worktree (the DoD's deterministic check surface). Core ``chorus``
stays policy-free; the floor policy is imported here from the PM package (a composition layer).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger
from chorus.ledger._models import Claim, DecisionRecord, RejectedAlternative
from chorus.lifecycle import CapabilityService, ClaimDraft
from chorus_employee.pm._decision import clears_floor, render_decision_mirror
from chorus_tools._shared import write_json

_DECISION_MIRROR = "decision.json"


class _ClaimIn(BaseModel):
    """One cited fact the decision rests on."""

    text: str = Field(min_length=1, description="the fact, stated plainly")
    source_url: str = Field(min_length=1, description="the citation URL that grounds this fact")
    confidence: float = Field(
        ge=0.0, le=1.0, description="how strongly the source supports it (0..1)"
    )


class _RejectedIn(BaseModel):
    """One option the decision considered and rejected."""

    option: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class RecordDecisionInput(BaseModel):
    """Arguments for ``record_decision`` — the whole decision plus its cited claims, in one call."""

    option: str = Field(min_length=1, description="the bet you are choosing, in one line")
    rationale: str = Field(min_length=1, description="why — decisive, not a list of open questions")
    confidence: float = Field(ge=0.0, le=1.0, description="your confidence in this call (0..1)")
    outcome_metric: str = Field(
        min_length=1, description="the metric that should move if you're right"
    )
    revisit_trigger: str = Field(
        min_length=1,
        description="what would reopen this — 'if metric flat within window W, revisit'",
    )
    rejected_alternatives: list[_RejectedIn] = Field(
        default_factory=list, description="the options you considered and rejected, with reasons"
    )
    claims: list[_ClaimIn] = Field(
        default_factory=list,
        description="the cited facts the decision rests on (from your research)",
    )


class RecordDecisionTool(BaseTool):
    """Record the PM's decision as an immutable, cited ledger object (§10), gated by the confidence floor."""

    name = "record_decision"
    description = (
        "Record your product decision as an immutable, cited ledger object. Supply the option, "
        "rationale, confidence, outcome metric, revisit trigger, rejected alternatives, and the claims "
        "(each with a source_url). Refused if your confidence is below the floor without cited "
        "evidence — gather evidence with the researcher first, then call again."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=30.0)
    input_model = RecordDecisionInput

    def __init__(self, ledger: Ledger) -> None:
        self._service = CapabilityService(ledger)

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = RecordDecisionInput.model_validate(input)
        except ValidationError as exc:
            return ToolResult(
                content=f"refused: malformed record_decision input — {exc}", is_error=True
            )

        if not clears_floor(confidence=args.confidence, claim_count=len(args.claims)):
            return self._below_floor(args)

        beat = BeatContext.read(ctx.working_dir)
        outcome = self._service.record_decision(
            task_id=beat.task_id,
            revision=beat.run_id,
            option=args.option,
            rationale=args.rationale,
            confidence=args.confidence,
            outcome_metric=args.outcome_metric,
            revisit_trigger=args.revisit_trigger,
            rejected=[
                RejectedAlternative(option=r.option, reason=r.reason)
                for r in args.rejected_alternatives
            ],
            claims=[
                ClaimDraft(text=c.text, source_url=c.source_url, confidence=c.confidence)
                for c in args.claims
            ],
        )
        # Mirror the CANONICAL recorded decision (the immutable ledger row), never this call's input:
        # on an idempotent re-fire ``outcome.record`` is the already-recorded decision, so decision.json
        # (and the plan built from it) can never drift off the ledger. ``record`` is set on both paths.
        record, claims = outcome.record, outcome.claims
        assert (
            record is not None
        )  # record_decision always returns the canonical row on a write path
        self._mirror(ctx.working_dir, record, claims)
        if outcome.idempotent:
            return self._already_recorded(record, len(claims))
        return ToolResult(
            content=(
                f"Decision {record.id} recorded · confidence {record.confidence:.2f} · "
                f"{len(claims)} cited claims · floor cleared."
            ),
            structured={
                "status": "success",
                "decision_id": record.id,
                "confidence": record.confidence,
                "claims": len(claims),
                "next_actions": [f"write plan.md referencing decision {record.id}"],
                "artifacts": [_DECISION_MIRROR, record.id],
            },
        )

    @staticmethod
    def _already_recorded(record: DecisionRecord, claim_count: int) -> ToolResult:
        """A second call this beat is a no-op: the recorded decision is immutable and stands."""
        return ToolResult(
            content=(
                f"Already recorded this beat: {record.id} — {record.option!r}. A decision is immutable "
                "within a beat, so this call did NOT change it; decision.json still reflects the "
                "recorded decision. Write plan.md to match the recorded decision above."
            ),
            structured={
                "status": "already_recorded",
                "decision_id": record.id,
                "option": record.option,
                "confidence": record.confidence,
                "claims": claim_count,
                "next_actions": [f"write plan.md referencing decision {record.id}"],
                "artifacts": [_DECISION_MIRROR, record.id],
            },
        )

    @staticmethod
    def _below_floor(args: RecordDecisionInput) -> ToolResult:
        return ToolResult(
            content=(
                f"NOT recorded — confidence {args.confidence:.2f} is below the floor with "
                f"{len(args.claims)} cited claims. Gather evidence, then decide."
            ),
            structured={
                "status": "blocked",
                "reason": "insufficient_evidence",
                "next_actions": [
                    "spawn_subagent(name='researcher', prompt='<the evidence question>')",
                    "re-call record_decision with the returned claims and a grounded confidence",
                ],
                "stop_condition": "do not write plan.md until a decision is recorded",
            },
            is_error=True,
            metadata={"root_cause": "confidence-below-floor"},
        )

    @staticmethod
    def _mirror(working_dir: Path, record: DecisionRecord, claims: Sequence[Claim]) -> None:
        """Write ``decision.json`` from the canonical ledger row — the DoD floor's check surface.

        Mirrors the recorded ``DecisionRecord`` + ``Claim`` rows (not the caller's raw input) via the
        shared renderer, so the worktree file always equals the immutable ledger decision and its shape
        can never drift from the lander's re-derivation of the same file.
        """
        payload = render_decision_mirror(record, claims)
        write_json(working_dir / _DECISION_MIRROR, payload)


__all__ = ["RecordDecisionInput", "RecordDecisionTool"]
