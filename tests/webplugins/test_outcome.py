"""Branch tournament / offline-eval — score-and-rank, not boolean pass/fail (spec GM §3)."""

from __future__ import annotations

import pytest

from chorus.webplugins import VariantScore, run_tournament

pytestmark = pytest.mark.unit


def _scores() -> list[VariantScore]:
    return [
        VariantScore("a", 0.8, {"power": 0.9}),
        VariantScore("b", 1.4, {"power": 0.95}),
        VariantScore("c", 1.1),
    ]


def test_ranks_descending_by_score() -> None:
    outcome = run_tournament(_scores(), top_k=1)
    assert [s.variant_id for s in outcome.ranked] == ["b", "c", "a"]
    assert outcome.best is not None and outcome.best.variant_id == "b"


def test_winners_are_the_top_k() -> None:
    outcome = run_tournament(_scores(), top_k=2)
    assert [s.variant_id for s in outcome.winners] == ["b", "c"]


def test_top_k_is_clamped_to_the_field_size() -> None:
    outcome = run_tournament(_scores(), top_k=10)
    assert len(outcome.winners) == 3  # never more variants than competed


def test_ties_break_deterministically_by_variant_id() -> None:
    tied = [VariantScore("z", 1.0), VariantScore("a", 1.0), VariantScore("m", 1.0)]
    outcome = run_tournament(tied, top_k=3)
    assert [s.variant_id for s in outcome.ranked] == ["a", "m", "z"]


def test_empty_tournament_has_no_best_or_winners() -> None:
    outcome = run_tournament([], top_k=1)
    assert outcome.best is None
    assert outcome.winners == ()


def test_negative_top_k_is_rejected() -> None:
    with pytest.raises(ValueError):
        run_tournament(_scores(), top_k=-1)
