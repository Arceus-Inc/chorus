"""Strategist subagent — the typed return contract (design doc §06, §10).

``StrategyBrief`` is a pydantic model: what the Strategist returns after framing the grounded bet
(the artifact path it wrote plus the structured bet and its cited evidence). ``model_validate``
parses+validates the raw return; ``strategy_output_schema`` is the JSON schema DERIVED from the
model (single source, no drift with a hand-written schema).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chorus_employee.marketer._subagents._strategist._schema import (
    EvidenceItem,
    StrategyBrief,
    strategy_output_schema,
)

pytestmark = pytest.mark.unit


def _payload() -> dict[str, object]:
    return {
        "brief_file": "strategy_brief.md",
        "hypothesis": "we believe platform engineers will adopt X because it cuts toil",
        "audience": "platform engineers at mid-size SaaS shops",
        "channel": "engineering blog + HN launch",
        "message_angle": "the release-night pager problem, not the feature list",
        "success_metric": "signups from the post; good = 200 in week one",
        "evidence": [
            {
                "claim": "competitor Y raised a $40M Series B in 2026",
                "source": "https://example.com/y",
            },
            {"claim": "GitOps adoption grew 30% YoY", "source": "CNCF 2026 survey"},
        ],
    }


class TestModelValidate:
    def test_roundtrips_well_formed_payload(self) -> None:
        brief = StrategyBrief.model_validate(_payload())
        assert brief.brief_file == "strategy_brief.md"
        assert brief.hypothesis.startswith("we believe")
        assert len(brief.evidence) == 2
        first = brief.evidence[0]
        assert isinstance(first, EvidenceItem)
        assert first.claim.startswith("competitor Y")
        assert first.source == "https://example.com/y"

    def test_empty_evidence_is_allowed(self) -> None:
        # An unverifiable bet still parses — the brief says so and leaves evidence empty (hard rule).
        payload = _payload() | {"evidence": []}
        brief = StrategyBrief.model_validate(payload)
        assert brief.evidence == []

    def test_rejects_missing_hypothesis(self) -> None:
        payload = {k: v for k, v in _payload().items() if k != "hypothesis"}
        with pytest.raises(ValidationError, match="hypothesis"):
            StrategyBrief.model_validate(payload)

    def test_rejects_blank_brief_file(self) -> None:
        # str_strip_whitespace + min_length=1: a whitespace-only path collapses to empty and fails.
        with pytest.raises(ValidationError, match="brief_file"):
            StrategyBrief.model_validate(_payload() | {"brief_file": "   "})

    def test_rejects_evidence_missing_source(self) -> None:
        bad = _payload() | {"evidence": [{"claim": "a fact with no citation"}]}
        with pytest.raises(ValidationError, match="source"):
            StrategyBrief.model_validate(bad)

    def test_rejects_evidence_empty_claim(self) -> None:
        bad = _payload() | {"evidence": [{"claim": "", "source": "s"}]}
        with pytest.raises(ValidationError, match="claim"):
            StrategyBrief.model_validate(bad)

    def test_rejects_non_list_evidence(self) -> None:
        with pytest.raises(ValidationError, match="evidence"):
            StrategyBrief.model_validate(_payload() | {"evidence": "nope"})


class TestOutputSchema:
    def test_schema_is_derived_from_the_model(self) -> None:
        # Single source of truth: the exported schema IS the model's json schema — nothing to drift.
        assert strategy_output_schema() == StrategyBrief.model_json_schema()

    def test_schema_is_an_object_requiring_the_bet_and_evidence(self) -> None:
        schema = strategy_output_schema()
        assert schema["type"] == "object"
        assert {"brief_file", "hypothesis", "evidence"} <= set(schema["required"])

    def test_model_fields_are_the_contract(self) -> None:
        assert set(StrategyBrief.model_fields) == {
            "brief_file",
            "hypothesis",
            "audience",
            "channel",
            "message_angle",
            "success_metric",
            "evidence",
        }
        assert set(EvidenceItem.model_fields) == {"claim", "source"}
