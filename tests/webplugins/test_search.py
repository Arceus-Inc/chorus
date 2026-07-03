"""Lead-search orchestration skeleton — query health, dedupe, exhaustiveness (spec GM §3)."""

from __future__ import annotations

import pytest

from chorus.webplugins import (
    Lead,
    LeadQuery,
    QueryHealth,
    QueryLevel,
    SearchPlatform,
    classify_query_health,
    dedupe_leads,
    exhaustiveness_stop,
    lead_dup_rate,
)

pytestmark = pytest.mark.unit


def _lead(link: str, platform: SearchPlatform = SearchPlatform.GOOGLE) -> Lead:
    return Lead(title="t", body="b", link=link, platform=platform)


def test_a_thin_result_set_is_a_ghost_town() -> None:
    # Below the floor the query is over-constrained — broaden/heal it, regardless of noise.
    assert classify_query_health(0, noisy=False) is QueryHealth.GHOST_TOWN
    assert classify_query_health(2, noisy=True) is QueryHealth.GHOST_TOWN


def test_a_full_but_noisy_result_set_is_a_haystack() -> None:
    assert classify_query_health(40, noisy=True) is QueryHealth.HAYSTACK


def test_a_full_clean_result_set_is_healthy() -> None:
    assert classify_query_health(40, noisy=False) is QueryHealth.HEALTHY


def test_the_floor_is_configurable() -> None:
    assert classify_query_health(5, noisy=False, min_results=10) is QueryHealth.GHOST_TOWN


def test_dedupe_drops_repeat_links_and_keeps_first_seen_order() -> None:
    leads = [_lead("a"), _lead("b"), _lead("a"), _lead("c"), _lead("b")]
    result = dedupe_leads(leads)
    assert [lead.link for lead in result.leads] == ["a", "b", "c"]
    assert result.duplicates_removed == 2


def test_dedupe_never_coalesces_empty_links() -> None:
    # An unknown link can't be proven a duplicate — keep every one (fail-open on identity).
    result = dedupe_leads([_lead(""), _lead(""), _lead("a")])
    assert len(result.leads) == 3
    assert result.duplicates_removed == 0


def test_dup_rate_is_the_duplicate_fraction() -> None:
    assert lead_dup_rate([_lead("a"), _lead("a"), _lead("b"), _lead("b")]) == 0.5
    assert lead_dup_rate([]) == 0.0
    assert lead_dup_rate([_lead("a"), _lead("b")]) == 0.0


def test_the_sweep_stops_once_it_saturates() -> None:
    assert exhaustiveness_stop(dup_rate=0.9, loop=1) == "saturated"


def test_the_sweep_stops_at_the_loop_budget() -> None:
    assert exhaustiveness_stop(dup_rate=0.0, loop=5) == "max_loops"


def test_a_fresh_low_dup_sweep_keeps_expanding() -> None:
    assert exhaustiveness_stop(dup_rate=0.01, loop=1) is None


def test_lead_query_and_levels_are_typed() -> None:
    q = LeadQuery(platform=SearchPlatform.LINKEDIN_XRAY, level=QueryLevel.ICP, query='"raised a seed"')
    assert q.platform is SearchPlatform.LINKEDIN_XRAY
    assert q.level is QueryLevel.ICP
    assert {p.value for p in SearchPlatform} >= {"google", "twitter", "reddit"}
