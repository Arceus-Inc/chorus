"""The Brand-Critic subagent's typed return contract (design doc §06, §10).

The Brand-Critic judges Mira's draft against the voice spec and returns a :class:`BrandVerdict` —
a decisive ``PASS``/``FAIL`` plus one :class:`Violation` per real breach it found (each quoting the
offending sentence, naming the rule, and suggesting a fix). ``violations`` is empty on ``PASS``;
``notes`` carries a concise summary (e.g. "no brand_spec.md found" on a fail-closed miss).

Pydantic models are the single source of truth: :func:`brand_verdict_output_schema` *derives* the
JSON schema the subagent's ``output_schema`` enforces via
:meth:`~pydantic.BaseModel.model_json_schema` (dream's ``jsonschema`` validator resolves its
``$ref``/``$defs``), and a caller parses the raw return with :meth:`BrandVerdict.model_validate` —
no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Violation(BaseModel):
    """One real brand-voice breach — the offending text, the rule, and a concrete fix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    sentence: str = Field(
        min_length=1, description="the offending text, quoted verbatim from the draft"
    )
    rule: str = Field(
        min_length=1, description="the brand rule or claim policy this sentence breaches"
    )
    fix: str = Field(min_length=1, description="a concrete suggested fix for the sentence")


class BrandVerdict(BaseModel):
    """Brand-Critic's return value: the decisive verdict plus every real violation behind it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verdict: Literal["PASS", "FAIL"] = Field(
        description="PASS when no real violations remain; FAIL otherwise"
    )
    violations: list[Violation] = Field(description="each real violation found; empty on PASS")
    notes: str = Field(
        default="",
        description="optional concise summary, e.g. 'no brand_spec.md found' on a fail-closed miss",
    )


def brand_verdict_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Brand-Critic's ``output_schema`` — derived from the model."""
    return BrandVerdict.model_json_schema()


__all__ = ["BrandVerdict", "Violation", "brand_verdict_output_schema"]
