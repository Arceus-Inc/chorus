"""The Code-Reviewer subagent's typed return contract (spec §06 — the verification swarm, red-team).

The Code-Reviewer is the adversary of §06: an independent, in-beat reviewer the engineer spawns to
red-team its own diff for the failure classes that *pass their own tests and fail in production* —
missing authorization, N+1 queries, injection, unbounded queries, absent rate limits, secrets in
code. It returns a :class:`CodeReviewVerdict`: a decisive ``cleared`` flag plus one
:class:`RiskFinding` per risk it found (category, severity, where, why, and the fix). It reviews,
never patches.

The contract is **self-consistent**: ``cleared`` cannot be ``True`` while any ``high``-severity
finding stands — clearing a diff you just flagged as high-risk is a contradiction the model cannot
express, so the engineer must fix the risk and re-review before it can be cleared.

Pydantic is the single source of truth: :func:`code_review_verdict_output_schema` derives the JSON
schema the subagent's ``output_schema`` enforces at runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Severity = Literal["high", "medium", "low"]

# The prod-failure classes the Backend Engineer is governed against (spec §01 crux) — the bugs that
# hide below the unit-test line because the agent wrote both the code and the tests.
RiskCategory = Literal[
    "missing_authz",
    "injection",
    "n_plus_1",
    "unbounded_query",
    "no_rate_limit",
    "secrets_in_code",
    "other",
]


class RiskFinding(BaseModel):
    """One risk the red-team review surfaced — what class, how bad, where, why, and the fix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    category: RiskCategory = Field(description="which prod-failure class this risk belongs to")
    severity: Severity = Field(description="high blocks the diff; medium/low are advisory")
    location: str = Field(min_length=1, description="where — file:line or function under review")
    detail: str = Field(
        min_length=1, description="the concrete risk: what fails, and under what input"
    )
    fix: str = Field(min_length=1, description="the specific change that removes the risk")


class CodeReviewVerdict(BaseModel):
    """Code-Reviewer's return: is the diff cleared of prod-failure risks, proven by named findings."""

    model_config = ConfigDict(str_strip_whitespace=True)

    cleared: bool = Field(
        description="True iff no high-severity risk remains — the diff is safe to land"
    )
    findings: list[RiskFinding] = Field(
        default_factory=list, description="one entry per risk found; empty means a clean review"
    )
    evidence: str = Field(
        min_length=1,
        description="how the diff was reviewed — what was read and what paths were traced",
    )

    @model_validator(mode="after")
    def _cleared_implies_no_high_risk(self) -> CodeReviewVerdict:
        """A ``cleared`` verdict may not carry a ``high`` finding — the grade must match the review."""
        if self.cleared and any(f.severity == "high" for f in self.findings):
            raise ValueError("cleared=True is invalid while a high-severity finding stands")
        return self


def code_review_verdict_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Code-Reviewer's ``output_schema`` — derived from the model."""
    return CodeReviewVerdict.model_json_schema()


__all__ = [
    "CodeReviewVerdict",
    "RiskCategory",
    "RiskFinding",
    "Severity",
    "code_review_verdict_output_schema",
]
