"""The PM's confidence policy — the pure rule the DoD floor and record_decision enforce (§10)."""

from __future__ import annotations

import pytest

from chorus_employee.pm._decision import CONFIDENCE_FLOOR, clears_floor

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("confidence", "claim_count", "expected"),
    [
        (0.9, 3, True),  # strong + cited
        (CONFIDENCE_FLOOR, 1, True),  # exactly at the floor, one cite
        (CONFIDENCE_FLOOR - 0.01, 3, False),  # below the floor — evidence can't rescue a weak call
        (0.9, 0, False),  # confident but uncited — never checkable
        (CONFIDENCE_FLOOR, 0, False),  # at the floor, no cite
    ],
)
def test_clears_floor(confidence: float, claim_count: int, expected: bool) -> None:
    assert clears_floor(confidence=confidence, claim_count=claim_count) is expected


def test_floor_is_a_sane_probability() -> None:
    assert 0.0 < CONFIDENCE_FLOOR < 1.0
