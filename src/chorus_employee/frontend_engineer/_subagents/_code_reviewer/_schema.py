"""The Code-Reviewer subagent's typed return contract (frontend engineer review layer).

The Code-Reviewer reads the Frontend Engineer's built app + its unit/e2e suites and returns a
:class:`ReviewVerdict` — a decisive ``PASS``/``FAIL`` plus one :class:`ReviewIssue` per real problem
(each naming the offending ``location``, the ``rule`` it breaches, its ``severity``, and a concrete
``fix``). ``issues`` is empty on a clean ``PASS``; ``notes`` carries a concise summary.

Pydantic models are the single source of truth (mirroring the Design-Critic's contract):
:func:`code_review_output_schema` derives the JSON schema the subagent's ``output_schema`` enforces via
:meth:`~pydantic.BaseModel.model_json_schema`, and a caller parses the raw return with
:meth:`ReviewVerdict.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewIssue(BaseModel):
    """One real code/test problem — where it is, the rule it breaks, its severity, and a concrete fix."""

    model_config = ConfigDict(str_strip_whitespace=True)

    location: str = Field(
        min_length=1,
        description="where the problem is — a file and, if useful, the symbol or line quoted verbatim",
    )
    rule: str = Field(
        min_length=1,
        description="the correctness, accessibility, resilience, maintainability, or test-quality rule breached",
    )
    severity: Literal["blocker", "major", "minor"] = Field(
        description=(
            "how much it matters: 'blocker' ships broken or inaccessible behaviour, or a hollow/"
            "tautological test that proves nothing; 'major' is a missing error/empty/loading state, a "
            "significant a11y gap, or an untested branch that matters; 'minor' is advisory polish. Any "
            "open blocker or major forces a FAIL."
        )
    )
    fix: str = Field(min_length=1, description="a concrete, actionable fix for the issue")


class ReviewVerdict(BaseModel):
    """Code-Reviewer's return value: the decisive verdict plus every real issue behind it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verdict: Literal["PASS", "FAIL"] = Field(
        description=(
            "FAIL when any blocker or major issue is open; PASS when only minors remain or none do — "
            "the bar is 'correct, accessible, resilient, and genuinely tested', not 'perfect'"
        )
    )
    issues: list[ReviewIssue] = Field(
        description="each real issue found, severity-tagged; empty on a clean PASS"
    )
    strengths: list[str] = Field(
        default_factory=list,
        description=(
            "what the code gets RIGHT — sound structure, real accessibility, meaningful tests — so the "
            "engineer converges the loop without regressing what already works"
        ),
    )
    notes: str = Field(
        default="", description="optional concise summary the engineer can act on at a glance"
    )


def code_review_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Code-Reviewer's ``output_schema`` — derived from the model."""
    return ReviewVerdict.model_json_schema()


__all__ = ["ReviewIssue", "ReviewVerdict", "code_review_output_schema"]
