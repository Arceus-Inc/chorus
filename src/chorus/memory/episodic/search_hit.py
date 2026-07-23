"""EpisodicSearchHit — BM25 row plus FTS5 match window (query recall)."""

from __future__ import annotations

from dataclasses import dataclass

from chorus.memory.episodic.models import SprintDelta


@dataclass(frozen=True)
class EpisodicSearchHit:
    """One keyword hit: the beat record and the FTS5 ``snippet()`` around the match."""

    record: SprintDelta
    snippet: str


__all__ = ["EpisodicSearchHit"]
