"""``EpisodicStore`` — episodic-memory facade with bounded recall reads (R0 + R2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from chorus._sqlite_migrations import MigrationRunner
from chorus.memory.episodic.models import SprintDelta
from chorus.memory.episodic.recall_filters import EpisodicQueryFilters
from chorus.memory.episodic.search_hit import EpisodicSearchHit
from chorus.memory.migrations import MIGRATIONS
from chorus.memory.repos import EpisodicRepo

_DB_NAME = "episodic.db"


class EpisodicStore:
    """Append-only per-beat episodic capture: open, migrate, expose repo reads + retention metadata."""

    def __init__(self, memory_dir: str | Path) -> None:
        root = Path(memory_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(root / _DB_NAME)
        self._conn.row_factory = sqlite3.Row
        MigrationRunner(MIGRATIONS).apply(self._conn)
        self._records = EpisodicRepo(self._conn)

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op."""
        self._records.append(delta)

    def get(self, run_id: str) -> SprintDelta | None:
        """The record for ``run_id``, or ``None`` if absent."""
        return self._records.get(run_id)

    def records_for(
        self,
        employee_id: str,
        *,
        limit: int | None = None,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[SprintDelta]:
        """Hot-tier records for one agent, newest first — bounded when ``limit`` is set."""
        return self._records.for_employee(employee_id, limit=limit, filters=filters)

    def search(
        self,
        query: str,
        *,
        employee_id: str | None = None,
        limit: int = 5,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[EpisodicSearchHit]:
        """Keyword search over intent+body, optionally scoped to one employee."""
        return self._records.search(query, employee_id=employee_id, limit=limit, filters=filters)

    def touch_recalled(self, run_ids: tuple[str, ...], *, now: datetime) -> None:
        """Mark beats as recalled (retrieval reinforcement)."""
        self._records.touch_recalled(run_ids, now=now)

    def pin_run_ids(self, employee_id: str, run_ids: tuple[str, ...]) -> None:
        """Pin cited run_ids after lattice apply."""
        self._records.pin_run_ids(employee_id, run_ids)

    def count(self) -> int:
        """Total records held."""
        return self._records.count()

    def close(self) -> None:
        self._conn.close()


__all__ = ["EpisodicStore"]
