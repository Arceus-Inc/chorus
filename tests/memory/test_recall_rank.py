"""Recall ranking — recency-primary with in-window tie-breaks (R2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.memory import SprintDelta
from chorus.memory._recall_rank import rank_keyword_hits, sort_recency_hits

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _delta(
    run_id: str,
    *,
    outcome: str = "done",
    recorded_at: datetime,
    pin_count: int = 0,
    intent: str = "work",
    body: str = "body",
) -> SprintDelta:
    return SprintDelta(
        run_id=run_id,
        task_id="t",
        employee_id="ada",
        scope="project",
        intent=intent,
        outcome=outcome,
        score=1.0,
        created_at=recorded_at,
        recorded_at=recorded_at,
        body=body,
        pin_count=pin_count,
    )


def test_yesterday_beats_old_failure_regardless_of_outcome() -> None:
    old_failure = _delta(
        "r_old",
        outcome="needs_changes",
        recorded_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
    )
    recent_done = _delta(
        "r_new",
        outcome="done",
        recorded_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
    )
    hits = sort_recency_hits([old_failure, recent_done], now=_NOW, limit=2)
    assert [d.run_id for d in hits] == ["r_new", "r_old"]


def test_failure_tie_breaks_above_done_in_same_hour() -> None:
    ts = datetime(2026, 7, 9, 10, 15, tzinfo=UTC)
    done = _delta("r_done", outcome="done", recorded_at=ts.replace(minute=30))
    failed = _delta("r_fail", outcome="needs_changes", recorded_at=ts.replace(minute=10))
    hits = sort_recency_hits([done, failed], now=_NOW, limit=2)
    assert [d.run_id for d in hits] == ["r_fail", "r_done"]


def test_keyword_prefers_recent_over_old_with_same_term() -> None:
    old = _delta(
        "r_old",
        intent="retry retry",
        body="retry retry",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    recent = _delta(
        "r_new",
        intent="retry retry",
        body="retry retry",
        recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
    )
    hits = rank_keyword_hits([old, recent], now=_NOW, limit=1)
    assert hits[0].run_id == "r_new"


def test_unpinned_old_loses_keyword_rank_to_recent_match() -> None:
    old = _delta(
        "r_old",
        intent="retry retry retry",
        body="retry retry retry",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    recent = _delta(
        "r_new",
        intent="retry retry retry",
        body="retry retry retry",
        recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
    )
    hits = rank_keyword_hits([recent, old], now=_NOW, limit=1)
    assert hits[0].run_id == "r_new"


def test_pinned_old_still_retrievable_in_keyword_top_k() -> None:
    old_pinned = _delta(
        "r_old",
        intent="retry",
        body="retry",
        recorded_at=datetime(2026, 1, 1, tzinfo=UTC),
        pin_count=1,
    )
    recent = _delta(
        "r_new",
        intent="retry",
        body="retry",
        recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
    )
    hits = rank_keyword_hits([recent, old_pinned], now=_NOW, limit=2)
    assert {h.run_id for h in hits} == {"r_new", "r_old"}
