"""Pure recall ranking — recency-primary with in-window tie-breaks (R2).

Episodic pull stays simple: newest beats first. Failure and pin signals reorder only within a
recent hour bucket; they never promote an old beat above a newer one.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from chorus.memory._models import SprintDelta

RECENT_WINDOW_DAYS = 7
_TAU_DAYS = 14.0
_FAILURE_OUTCOMES = frozenset({"needs_changes", "blocked", "incomplete"})


def recorded_at(delta: SprintDelta) -> datetime:
    """Wall time the beat was captured — the recency axis."""
    ts = delta.recorded_at or delta.created_at
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts


def sort_recency_hits(
    deltas: list[SprintDelta],
    *,
    now: datetime,
    limit: int,
) -> list[SprintDelta]:
    """Newest first; tie-break failures and pins only inside the recent window, same hour."""
    if not deltas:
        return []
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    ordered = sorted(deltas, key=lambda d: _recency_sort_key(d, now=now), reverse=True)
    return ordered[:limit]


def rank_keyword_hits(
    hits: list[SprintDelta],
    *,
    now: datetime,
    limit: int,
    tau_days: float = _TAU_DAYS,
) -> list[SprintDelta]:
    """BM25-ordered pool re-ranked by recency decay; pinned rows skip decay."""
    if not hits:
        return []
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    def score(index: int, delta: SprintDelta) -> float:
        bm25_proxy = 1.0 / (1.0 + index)
        age_days = (now - recorded_at(delta)).total_seconds() / 86_400.0
        decay = 1.0 if delta.pin_count > 0 else math.exp(-age_days / tau_days)
        return bm25_proxy * decay

    ranked = sorted(enumerate(hits), key=lambda pair: score(pair[0], pair[1]), reverse=True)
    return [delta for _, delta in ranked[:limit]]


def _recency_sort_key(delta: SprintDelta, *, now: datetime) -> tuple[float, int, int, float]:
    ts = recorded_at(delta)
    age_days = (now - ts).total_seconds() / 86_400.0
    in_window = age_days <= RECENT_WINDOW_DAYS
    hour_start = ts.replace(minute=0, second=0, microsecond=0)
    tie = (_failure_rank(delta.outcome), delta.pin_count) if in_window else (0, 0)
    return (hour_start.timestamp(), tie[0], tie[1], ts.timestamp())


def _failure_rank(outcome: str) -> int:
    """Higher ranks first when tie-breaking inside the recent window."""
    return 1 if outcome in _FAILURE_OUTCOMES else 0


__all__ = [
    "RECENT_WINDOW_DAYS",
    "rank_keyword_hits",
    "recorded_at",
    "sort_recency_hits",
]
