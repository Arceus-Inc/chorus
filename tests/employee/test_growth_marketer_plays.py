"""The play recommender — ranking go-to-market plays via the branch tournament (spec GM §3)."""

from __future__ import annotations

import pytest

from chorus.webplugins import SearchPlatform
from chorus_employee.growth_marketer import (
    Play,
    ScoredPlay,
    SearchStrategy,
    recommend_plays,
)

pytestmark = pytest.mark.unit


def _play(pid: str) -> Play:
    return Play(id=pid, title=pid, icp="seed-stage AI teams", context="just raised", signal="hiring")


def test_recommend_ranks_plays_best_first_and_ships_the_top_k() -> None:
    scored = [
        ScoredPlay(_play("a"), 0.4),
        ScoredPlay(_play("b"), 0.9),
        ScoredPlay(_play("c"), 0.7),
    ]
    rec = recommend_plays(scored, top_k=2)
    assert [p.id for p in rec.ranked] == ["b", "c", "a"]
    assert [p.id for p in rec.winners] == ["b", "c"]
    assert rec.top is not None and rec.top.id == "b"


def test_recommend_breaks_ties_deterministically_by_id() -> None:
    rec = recommend_plays([ScoredPlay(_play("b"), 0.5), ScoredPlay(_play("a"), 0.5)], top_k=1)
    # equal score → stable order by the tournament's id tie-break.
    assert [p.id for p in rec.ranked] == ["a", "b"]
    assert [p.id for p in rec.winners] == ["a"]


def test_recommend_on_no_candidates_is_empty() -> None:
    rec = recommend_plays([], top_k=3)
    assert rec.ranked == () and rec.winners == ()
    assert rec.top is None


def test_recommend_rejects_duplicate_play_ids() -> None:
    with pytest.raises(ValueError, match="duplicate play id"):
        recommend_plays([ScoredPlay(_play("a"), 0.1), ScoredPlay(_play("a"), 0.2)])


def test_search_strategy_carries_the_angle_and_platform() -> None:
    strat = SearchStrategy(
        title="Leadership vacuum",
        concept="a departed CTO signals an interim-leadership need",
        sample_query='"stepping down as CTO"',
        platform=SearchPlatform.LINKEDIN_NATIVE,
    )
    assert strat.platform is SearchPlatform.LINKEDIN_NATIVE
    assert "CTO" in strat.sample_query
