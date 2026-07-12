"""EpisodicRecallService — list/search/get_run kernel (R7 + R8 + R9)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from chorus.memory.episodic.models import SprintDelta
from chorus.memory.episodic.recall_filters import EpisodicQueryFilters
from chorus.memory.episodic.recall_rank import RecallProfile, rerank_keyword_hits, sort_recency_hits
from chorus.memory.episodic.store import EpisodicStore

_SEARCH_CANDIDATE_POOL = 20
_FILTER_CANDIDATE_POOL = 40


@dataclass(frozen=True)
class RecallResult:
    """Bounded recall hits plus the resolved retrieval mode and profile."""

    mode: Literal["recency", "search"]
    profile: RecallProfile
    hits: tuple[SprintDelta, ...]


class EpisodicRecallService:
    """Employee-scoped episodic reads — recency, filtered search, and drill-down."""

    def __init__(self, store: EpisodicStore) -> None:
        self._store = store

    def recall(
        self,
        employee_id: str,
        *,
        own_run_id: str,
        query: str | None = None,
        filters: EpisodicQueryFilters | None = None,
        profile: RecallProfile = "general",
        limit: int = 5,
        now: datetime | None = None,
    ) -> RecallResult:
        ts = now or datetime.now(tz=UTC)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        active = filters if filters is not None and filters.is_active() else None
        if query is None and active is None:
            pool = self._store.records_for(employee_id, limit=limit + 1)
            hits = _exclude_own(pool, own_run_id=own_run_id)
            ranked = sort_recency_hits(hits, now=ts, limit=limit, profile=profile)
            return RecallResult(mode="recency", profile=profile, hits=tuple(ranked))

        if query is None:
            pool = self._store.records_for(
                employee_id,
                limit=_FILTER_CANDIDATE_POOL,
                filters=active,
            )
            hits = _exclude_own(pool, own_run_id=own_run_id)
            ranked = sort_recency_hits(hits, now=ts, limit=limit, profile=profile)
            return RecallResult(mode="search", profile=profile, hits=tuple(ranked))

        pool_size = _FILTER_CANDIDATE_POOL if active is not None else _SEARCH_CANDIDATE_POOL
        candidates = self._store.search(
            query,
            employee_id=employee_id,
            limit=pool_size,
            filters=active,
        )
        hits = _exclude_own(candidates, own_run_id=own_run_id)
        ranked = rerank_keyword_hits(hits, profile=profile, now=ts, limit=limit)
        return RecallResult(mode="search", profile=profile, hits=tuple(ranked))

    def get_run(self, employee_id: str, run_id: str) -> SprintDelta | None:
        delta = self._store.get(run_id)
        if delta is None or delta.employee_id != employee_id:
            return None
        return delta

    def touch_recalled(self, run_ids: tuple[str, ...], *, now: datetime) -> None:
        """Best-effort retrieval reinforcement for returned hits."""
        self._store.touch_recalled(run_ids, now=now)


def _exclude_own(deltas: list[SprintDelta], *, own_run_id: str) -> list[SprintDelta]:
    return [delta for delta in deltas if delta.run_id != own_run_id]


__all__ = ["EpisodicRecallService", "RecallResult"]
