"""The UI-Tester subagent's typed return contract (frontend engineer review layer).

The UI-Tester judges whether the Frontend Engineer's tests actually PROVE the app works — that the
e2e suite drives the real UI and asserts user-visible outcomes, that the captured runs are genuine and
green, and that the flows the intent implies are covered. It returns a :class:`UiTestVerdict` — a
decisive ``PASS``/``FAIL`` plus one :class:`CoverageGap` per missing or hollow piece of proof.

Pydantic models are the single source of truth (mirroring the Design-Critic's contract):
:func:`ui_test_output_schema` derives the JSON schema the subagent's ``output_schema`` enforces, and a
caller parses the raw return with :meth:`UiTestVerdict.model_validate`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class CoverageGap(BaseModel):
    """One hole in the proof — a flow left untested, a hollow assertion, or evidence that isn't real."""

    model_config = ConfigDict(str_strip_whitespace=True)

    flow: str = Field(
        min_length=1,
        description="the user flow or claim left unproven, named as a user would describe it",
    )
    rule: str = Field(
        min_length=1,
        description="why it's a gap — untested critical flow, tautological assertion, or unreal/failing evidence",
    )
    severity: Literal["blocker", "major", "minor"] = Field(
        description=(
            "how much it matters: 'blocker' means the core flow the intent asked for is not genuinely "
            "proven (no e2e drives it, the assertion is hollow, or the captured run is fabricated/red); "
            "'major' is a meaningful secondary flow or error path with no coverage; 'minor' is a "
            "nice-to-have extra check. Any open blocker or major forces a FAIL."
        )
    )
    fix: str = Field(
        min_length=1, description="the concrete test to add or strengthen to close the gap"
    )


class UiTestVerdict(BaseModel):
    """UI-Tester's return value: the decisive verdict plus every gap in the proof behind it."""

    model_config = ConfigDict(str_strip_whitespace=True)

    verdict: Literal["PASS", "FAIL"] = Field(
        description=(
            "FAIL when any blocker or major gap is open — the app's core behaviour is not genuinely "
            "proven by a real, green run; PASS when the critical flows are exercised and asserted and "
            "only minors remain"
        )
    )
    gaps: list[CoverageGap] = Field(
        description="each gap in the proof, severity-tagged; empty on a clean PASS"
    )
    covered_flows: list[str] = Field(
        default_factory=list,
        description="the user flows the suite genuinely exercises and asserts — the proof that stands",
    )
    notes: str = Field(
        default="", description="optional concise summary, e.g. which captured run was inspected"
    )


def ui_test_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the UI-Tester's ``output_schema`` — derived from the model."""
    return UiTestVerdict.model_json_schema()


__all__ = ["CoverageGap", "UiTestVerdict", "ui_test_output_schema"]
