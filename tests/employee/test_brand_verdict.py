"""Brand-Critic subagent — the typed return contract (design doc §06, §10).

``BrandVerdict`` is a pydantic model: what the Brand-Critic returns after judging a draft (a
decisive PASS/FAIL plus one entry per real violation). ``model_validate`` parses+validates the raw
return; ``brand_verdict_output_schema`` is the JSON schema DERIVED from the model (single source).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus_employee.marketer._subagents._brand_critic._schema import (
    BrandVerdict,
    Violation,
    brand_verdict_output_schema,
)

pytestmark = pytest.mark.unit


class TestModelValidate:
    def test_pass_with_no_violations(self) -> None:
        verdict = BrandVerdict.model_validate({"verdict": "PASS", "violations": []})
        assert verdict.verdict == "PASS"
        assert verdict.violations == []
        assert verdict.notes == ""  # optional, defaults to empty

    def test_fail_with_violations(self) -> None:
        payload = {
            "verdict": "FAIL",
            "violations": [
                {
                    "sentence": "cuts release time 40%",
                    "rule": "unsubstantiated metric stated as fact",
                    "fix": "hedge it: 'is designed to reduce release time'",
                }
            ],
            "notes": "one metric needs a citation",
        }
        verdict = BrandVerdict.model_validate(payload)
        assert verdict.verdict == "FAIL"
        assert len(verdict.violations) == 1
        first = verdict.violations[0]
        assert isinstance(first, Violation)
        assert first.rule.startswith("unsubstantiated")
        assert verdict.notes == "one metric needs a citation"

    def test_rejects_verdict_outside_the_enum(self) -> None:
        with pytest.raises(ValidationError, match="verdict"):
            BrandVerdict.model_validate({"verdict": "MAYBE", "violations": []})

    def test_rejects_missing_verdict(self) -> None:
        with pytest.raises(ValidationError, match="verdict"):
            BrandVerdict.model_validate({"violations": []})

    def test_rejects_missing_violations(self) -> None:
        with pytest.raises(ValidationError, match="violations"):
            BrandVerdict.model_validate({"verdict": "PASS"})

    def test_rejects_violation_missing_fix(self) -> None:
        bad = {"verdict": "FAIL", "violations": [{"sentence": "x", "rule": "y"}]}
        with pytest.raises(ValidationError, match="fix"):
            BrandVerdict.model_validate(bad)

    def test_rejects_violation_empty_sentence(self) -> None:
        bad = {"verdict": "FAIL", "violations": [{"sentence": "", "rule": "y", "fix": "z"}]}
        with pytest.raises(ValidationError, match="sentence"):
            BrandVerdict.model_validate(bad)


class TestOutputSchema:
    def test_schema_is_derived_from_the_model(self) -> None:
        assert brand_verdict_output_schema() == BrandVerdict.model_json_schema()

    def test_verdict_is_a_pass_fail_enum(self) -> None:
        schema = brand_verdict_output_schema()
        assert schema["type"] == "object"
        assert set(schema["required"]) >= {"verdict", "violations"}
        assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]

    def test_model_fields_are_the_contract(self) -> None:
        assert set(BrandVerdict.model_fields) == {"verdict", "violations", "notes"}
        assert set(Violation.model_fields) == {"sentence", "rule", "fix"}
