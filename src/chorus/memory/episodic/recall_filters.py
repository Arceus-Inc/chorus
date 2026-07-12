"""SQL filter clauses for episodic list/search (R7)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chorus.ledger.repos._base import to_iso


@dataclass(frozen=True)
class EpisodicQueryFilters:
    """Optional pre-filters applied before recall ranking."""

    task_id: str | None = None
    since: datetime | None = None

    def is_active(self) -> bool:
        return self.task_id is not None or self.since is not None


def filter_clause(
    filters: EpisodicQueryFilters | None,
    *,
    alias: str = "",
) -> tuple[str, list[object]]:
    """Return ``AND …`` SQL fragment and bound params for episodic_record columns."""
    if filters is None or not filters.is_active():
        return "", []
    prefix = f"{alias}." if alias else ""
    clauses: list[str] = []
    params: list[object] = []
    if filters.task_id is not None:
        clauses.append(f"{prefix}task_id = ?")
        params.append(filters.task_id)
    if filters.since is not None:
        clauses.append(f"{prefix}recorded_at >= ?")
        params.append(to_iso(filters.since))
    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


__all__ = ["EpisodicQueryFilters", "filter_clause"]
