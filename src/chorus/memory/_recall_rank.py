"""Pure recall ranking — recency-primary with in-window tie-breaks (R2 + R9)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from chorus.memory._models import SprintDelta

RECENT_WINDOW_DAYS = 7
_TAU_DAYS = 14.0
_FAILURE_BOOST = 0.15
_FAILURE_OUTCOMES = frozenset({"needs_changes", "blocked", "incomplete"})

RecallProfile = Literal["general", "debug"]
_DEBUG_RANK_NOTE = "surfaced — debug profile and this beat failed"


def recorded_at(delta: SprintDelta) -> datetime:
    """Wall time the beat was captured — the recency axis."""
    ts = delta.recorded_at or delta.created_at
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def is_failure_outcome(outcome: str) -> bool:
    """Whether an episodic outcome counts as a failure for debug rerank."""
    return outcome in _FAILURE_OUTCOMES


def sort_recency_hits(
    deltas: list[SprintDelta],
    *,
    now: datetime,
    limit: int,
    profile: RecallProfile = "general",
) -> list[SprintDelta]:
    """Newest first; debug profile surfaces failures before successes on the same thread."""
    if not deltas:
        return []
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    if profile == "debug":
        ordered = sorted(
            deltas,
            key=lambda d: (_failure_rank(d.outcome), recorded_at(d).timestamp()),
            reverse=True,
        )
        return ordered[:limit]

    ordered = sorted(deltas, key=lambda d: _recency_sort_key(d, now=now), reverse=True)
    return ordered[:limit]


def rerank_keyword_hits(
    hits: list[SprintDelta],
    *,
    profile: RecallProfile,
    now: datetime,
    limit: int,
    tau_days: float = _TAU_DAYS,
) -> list[SprintDelta]:
    """BM25 pool re-ranked by recency decay; debug profile boosts failure outcomes."""
    if not hits:
        return []
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    def score(index: int, delta: SprintDelta) -> float:
        bm25_proxy = 1.0 / (1.0 + index)
        age_days = (now - recorded_at(delta)).total_seconds() / 86_400.0
        decay = 1.0 if delta.pin_count > 0 else math.exp(-age_days / tau_days)
        total = bm25_proxy * decay
        if profile == "debug" and is_failure_outcome(delta.outcome):
            total += _FAILURE_BOOST
        return total

    ranked = sorted(enumerate(hits), key=lambda pair: score(pair[0], pair[1]), reverse=True)
    return [delta for _, delta in ranked[:limit]]


def rank_keyword_hits(
    hits: list[SprintDelta],
    *,
    now: datetime,
    limit: int,
    tau_days: float = _TAU_DAYS,
) -> list[SprintDelta]:
    """Backward-compatible general-profile keyword rerank."""
    return rerank_keyword_hits(
        hits,
        profile="general",
        now=now,
        limit=limit,
        tau_days=tau_days,
    )


def _recency_sort_key(delta: SprintDelta, *, now: datetime) -> tuple[float, int, int, float]:
    ts = recorded_at(delta)
    age_days = (now - ts).total_seconds() / 86_400.0
    in_window = age_days <= RECENT_WINDOW_DAYS
    hour_start = ts.replace(minute=0, second=0, microsecond=0)
    tie = (_failure_rank(delta.outcome), delta.pin_count) if in_window else (0, 0)
    return (hour_start.timestamp(), tie[0], tie[1], ts.timestamp())


def _failure_rank(outcome: str) -> int:
    """Higher ranks first when tie-breaking inside the recent window."""
    return 1 if is_failure_outcome(outcome) else 0


__all__ = [
    "RECENT_WINDOW_DAYS",
    "_DEBUG_RANK_NOTE",
    "RecallProfile",
    "is_failure_outcome",
    "rank_keyword_hits",
    "recorded_at",
    "rerank_keyword_hits",
    "sort_recency_hits",
]
