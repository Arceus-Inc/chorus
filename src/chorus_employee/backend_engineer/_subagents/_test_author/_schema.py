"""The Test-Author subagent's typed return contract (spec §06 — the validation sandwich, 'pre').

The Test-Author is handed the diff + acceptance criteria and writes honeycomb-shaped tests for the
change — integration-heavy against real dependencies, a thin e2e/contract layer, unit for the logic
that isn't visible at the boundary. It writes tests, never production code, and returns a
:class:`TestPlanVerdict`: whether it authored (and ran green), the test files it wrote, the behaviours
it now covers, and how it ran them.

The contract is **self-consistent**: ``authored`` cannot be ``True`` unless it names at least one test
file and one covered behaviour — a claim of tests written with nothing to show is a contradiction.

Pydantic is the single source of truth: :func:`plan_verdict_output_schema` derives the JSON schema
the subagent's ``output_schema`` enforces at runtime, and a caller parses the raw return with
:meth:`TestPlanVerdict.model_validate` — no hand-written schema to drift.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TestPlanVerdict(BaseModel):
    """Test-Author's return: what tests it wrote, what they cover, and that they ran green."""

    # Not a pytest test class despite the ``Test`` prefix — tell the collector to skip it.
    __test__ = False

    model_config = ConfigDict(str_strip_whitespace=True)

    authored: bool = Field(description="True iff it wrote tests for the change AND ran them green")
    files: list[str] = Field(
        description="the test files written or extended (worktree-relative); empty only if not authored"
    )
    covers: list[str] = Field(
        description="the behaviours the new tests now cover; empty only if not authored"
    )
    red_evidence: str = Field(
        default="",
        description=(
            "TDD's RED proof: the command run BEFORE the implementation existed and its FAILING "
            "output — the tests were seen to fail for the right reason first. Required when authored"
        ),
    )
    evidence: str = Field(
        min_length=1, description="how the tests were run to GREEN — the command and its result"
    )

    @model_validator(mode="after")
    def _authored_shows_its_work(self) -> TestPlanVerdict:
        """An ``authored`` verdict names a test file, a covered behaviour, and its RED proof.

        Test-first (TDD) is the point: a claim of authored tests with no evidence they were seen
        failing first is a claim you could not have written test-first — a contradiction.
        """
        if self.authored and (not self.files or not self.covers):
            raise ValueError(
                "authored=True requires at least one test file and one covered behaviour"
            )
        if self.authored and not self.red_evidence:
            raise ValueError(
                "authored=True requires red_evidence — the failing run seen BEFORE implementing (TDD)"
            )
        return self


def plan_verdict_output_schema() -> dict[str, Any]:
    """The JSON schema handed to the Test-Author's ``output_schema`` — derived from the model."""
    return TestPlanVerdict.model_json_schema()


__all__ = ["TestPlanVerdict", "plan_verdict_output_schema"]
