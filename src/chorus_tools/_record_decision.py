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

import json
from pathlib import Path

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

from chorus.heartbeat import BeatContext
from chorus.ledger import SqliteLedger
from chorus.ledger._models import RejectedAlternative
from chorus.lifecycle import CapabilityService, ClaimDraft
from chorus_employee.pm._decision import clears_floor

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

    def __init__(self, ledger: SqliteLedger) -> None:
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
        self._mirror(ctx.working_dir, args, outcome.decision_id)
        return ToolResult(
            content=(
                f"Decision {outcome.decision_id} recorded · confidence {args.confidence:.2f} · "
                f"{len(args.claims)} cited claims · floor cleared."
            ),
            structured={
                "status": "success",
                "decision_id": outcome.decision_id,
                "confidence": args.confidence,
                "claims": len(args.claims),
                "next_actions": [f"write plan.md referencing decision {outcome.decision_id}"],
                "artifacts": [_DECISION_MIRROR, outcome.decision_id],
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
    def _mirror(working_dir: Path, args: RecordDecisionInput, decision_id: str) -> None:
        """Write ``decision.json`` — the DoD floor's check surface + a human-diffable record."""
        payload = {"decision_id": decision_id, **args.model_dump()}
        (working_dir / _DECISION_MIRROR).write_text(json.dumps(payload, indent=2), encoding="utf-8")


__all__ = ["RecordDecisionInput", "RecordDecisionTool"]
