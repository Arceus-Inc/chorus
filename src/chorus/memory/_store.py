"""``EpisodicStore`` — the episodic-memory facade (spec 07). Mirrors ``chorus.ledger.SqliteLedger``.

Opens (creating + migrating) a per-org SQLite file at ``{memory_dir}/episodic.db`` and composes the
one repo aggregate (:class:`~chorus.memory.repos.EpisodicRepo`). The append-only ``episodic_record``
table *is* the audit trail — the md-in-git substrate this replaced bought a git history that never
existed in practice (the memory dir is git-excluded), so "rows never mutate" carries that guarantee
instead. ``record_file`` / ``record_fts`` stay disposable indexes lattice or a rebuild may recreate.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from chorus.ledger._migrations import MigrationRunner
from chorus.memory._models import SprintDelta
from chorus.memory.migrations import MIGRATIONS
from chorus.memory.repos import EpisodicRepo

_DB_NAME = "episodic.db"


class EpisodicStore:
    """Append-only per-beat episodic capture (spec 07 §3): open, migrate, expose the repo's reads."""

    def __init__(self, memory_dir: str | Path) -> None:
        root = Path(memory_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(root / _DB_NAME)
        self._conn.row_factory = sqlite3.Row
        MigrationRunner(MIGRATIONS).apply(self._conn)
        self._records = EpisodicRepo(self._conn)

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only)."""
        self._records.append(delta)

    def get(self, run_id: str) -> SprintDelta | None:
        """The record for ``run_id``, or ``None`` if absent."""
        return self._records.get(run_id)

    def records_for(self, employee_id: str) -> list[SprintDelta]:
        """Every record for one agent, newest first — the per-agent episodic stream."""
        return self._records.for_employee(employee_id)

    def records_touching(self, paths: tuple[str, ...]) -> list[SprintDelta]:
        """Records whose fingerprint overlaps any of ``paths`` — the structural pre-filter."""
        return self._records.touching(paths)

    def search(self, query: str, *, limit: int = 5) -> list[SprintDelta]:
        """Keyword search over intent+body, best match first — the BM25 half of retrieval."""
        return self._records.search(query, limit=limit)

    def count(self) -> int:
        """Total records held."""
        return self._records.count()

    def close(self) -> None:
        self._conn.close()


__all__ = ["EpisodicStore", "SprintDelta"]
