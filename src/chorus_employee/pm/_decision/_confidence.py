"""The PM's confidence policy — the rule the DoD floor and the record_decision tool enforce (§10).

A pure, side-effect-free predicate: it holds no state and touches no ledger, so it is trivially
testable and shared by both the in-tool check (Slice 3) and the out-of-beat DoD floor (Slice 4). The
policy is the §10 wager made mechanical — confidence gates the *strength* of a recommendation, and a
cited claim makes it *checkable* (faithfulness). A confident-sounding decision with no evidence never
clears.
"""

from __future__ import annotations

CONFIDENCE_FLOOR = 0.7
"""Below this, a recommendation is not shippable as a hedge — it must be backed by cited evidence."""


def clears_floor(*, confidence: float, claim_count: int) -> bool:
    """Whether a decision clears the grounding floor: confidence at/above the floor AND ≥ 1 cited claim.

    Example: ``clears_floor(confidence=0.82, claim_count=2)`` → ``True``;
    ``clears_floor(confidence=0.4, claim_count=5)`` → ``False`` (evidence can't rescue a weak call).
    """
    return confidence >= CONFIDENCE_FLOOR and claim_count >= 1


__all__ = ["CONFIDENCE_FLOOR", "clears_floor"]
