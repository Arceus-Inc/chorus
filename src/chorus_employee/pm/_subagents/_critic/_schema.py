"""The Critic subagent's typed return contract (pm design doc §06, §09/§10).

The Critic red-teams the PM's drafted decision and returns a :class:`DecisionCritique` — a decisive
``PASS``/``REVISE`` verdict plus one :class:`Finding` per real weakness (each naming the dimension it
breaches, the specific issue, and a concrete fix), followed by the §06 subagent contract: a ``new_angle``
the PM should validate and a durable ``learnings`` note for the skill base. ``findings`` is empty on
``PASS``; ``notes`` carries a concise summary (e.g. "no plan.md found" on a fail-closed miss).

Pydantic models are the single source of truth: :func:`decision_critique_output_schema` *derives* the
JSON schema the subagent's ``output_schema`` enforces via :meth:`~pydantic.BaseModel.model_json_schema`
(dream's ``jsonschema`` validator resolves its ``$ref``/``$defs``), and a caller parses the raw return
with :meth:`DecisionCritique.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The dimensions a decision can be weak on — the Critic must categorise each finding, so the PM can see
# WHICH quality axis failed (and the DoD floor can only check the mechanical ones).
Dimension = Literal[
    "evidence_sufficiency",  # claims uncited, thin coverage, or a source that doesn't support the claim
    "options_real",  # fewer than two genuine alternatives, or straw-man rejections
    "confidence_calibration",  # stated confidence outruns the evidence coverage
    "revisit_trigger",  # missing/weak — no concrete signal that would reopen the decision
    "other",  # a real weakness that doesn't fit the four above
]


class Finding(BaseModel):
    """One real weakness in the decision — the dimension it breaches, the issue, and a concrete fix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    dimension: Dimension = Field(description="which decision-quality axis this weakness sits on")
    issue: str = Field(
        min_length=1,
        description="the specific weakness — quote or name the offending part of the decision",
    )
    fix: str = Field(
        min_length=1,
        description="a concrete change that would resolve it before the decision lands",
    )


class DecisionCritique(BaseModel):
    """The Critic's return value: the decisive verdict plus the real weaknesses and the §06 contract."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verdict: Literal["PASS", "REVISE"] = Field(
        description="PASS when the decision is sound (evidence sufficient, options real, confidence "
        "calibrated, revisit trigger present); REVISE when any finding must be addressed first"
    )
    findings: list[Finding] = Field(
        description="each real weakness the PM must address before recording; EMPTY on PASS — do not "
        "manufacture marginal findings to keep failing a sound decision"
    )
    new_angle: str = Field(
        min_length=1,
        description="a problem perspective the PM should validate — the 'new angle' half of the §06 "
        "subagent contract (say 'none material' if there genuinely is none)",
    )
    learnings: str = Field(
        min_length=1,
        description="a durable insight worth keeping for future decisions — the 'learnings' half of "
        "the §06 contract (feeds the skill base)",
    )
    notes: str = Field(
        default="",
        description="optional concise summary, e.g. 'no plan.md found' on a fail-closed miss",
    )


def decision_critique_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Critic subagent's ``output_schema`` — derived from the model."""
    return DecisionCritique.model_json_schema()


__all__ = ["DecisionCritique", "Dimension", "Finding", "decision_critique_output_schema"]
