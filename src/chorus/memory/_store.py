"""The SQLite-native episodic store — chorus owns the mechanism, lattice the policy (spec 07).

One record per beat, append-only (first-write-wins). The source of truth is a per-org SQLite file,
not markdown: the md-in-git substrate bought a git audit trail that never existed in practice (the
memory dir is git-excluded), so the honest properties — an immutable append-only source + a
rebuildable retrieval index — live in one SQLite file instead.

Tables:
- ``episodic_record`` — the immutable source row per beat (the audit trail is "rows never mutate").
- ``record_file``     — ``files_touched`` fanned out, one row per (run_id, path): the fingerprint
  pre-filter, so "records touching any of these paths" is a plain join, not a JSON scan.
- ``record_fts``      — an FTS5 index over intent+body (the BM25 half of retrieval); rebuildable.

Consolidation (episodic→semantic) stays lattice's job; this store only appends raw records and reads
them back.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic_record (
    run_id      TEXT PRIMARY KEY,
    task_id     TEXT NOT NULL,
    employee_id TEXT NOT NULL,
    scope       TEXT NOT NULL DEFAULT 'project',
    role        TEXT NOT NULL DEFAULT '',
    intent      TEXT NOT NULL DEFAULT '',
    outcome     TEXT NOT NULL DEFAULT '',
    score       REAL NOT NULL DEFAULT 0,
    body        TEXT NOT NULL DEFAULT '',
    artifacts   TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    recorded_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodic_employee ON episodic_record(employee_id, recorded_at);

CREATE TABLE IF NOT EXISTS record_file (
    run_id TEXT NOT NULL,
    path   TEXT NOT NULL,
    PRIMARY KEY (run_id, path)
);
CREATE INDEX IF NOT EXISTS idx_record_file_path ON record_file(path);

CREATE VIRTUAL TABLE IF NOT EXISTS record_fts USING fts5(run_id UNINDEXED, intent, body);
"""

_DB_NAME = "episodic.db"


@dataclass(frozen=True)
class SprintDelta:
    """The one raw episodic record chorus writes per beat (spec 07 §3).

    Every field is **derived from the run, never authored by the worker** — ``outcome``/``score``/
    ``artifacts``/``files_touched`` are copied verbatim from the run so the record is an honest trace,
    not a self-report; ``body`` is the entire raw agent account (reasoning + actions).
    """

    run_id: str
    task_id: str
    employee_id: str
    scope: str
    intent: str
    outcome: str
    score: float
    created_at: datetime
    role: str = ""
    recorded_at: datetime | None = None
    kind: str = "sprint_delta"
    artifacts: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    body: str = ""


class EpisodicStore:
    """Append-only SQLite store of per-beat episodic records (spec 07 §3).

    ``EpisodicStore(memory_dir)`` opens (creating) ``{memory_dir}/episodic.db``. A record is written
    once and never mutated — a re-append of the same ``run_id`` is an idempotent no-op (first write
    wins), which is exactly the append-only guarantee the md writer had. lattice's consolidating
    writer is the only thing that ever rewrites an existing record (the §4 seam).
    """

    def __init__(self, memory_dir: str | Path) -> None:
        root = Path(memory_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(root / _DB_NAME)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only, spec 07 §3)."""
        recorded = (delta.recorded_at or delta.created_at).isoformat()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO episodic_record "
            "(run_id, task_id, employee_id, scope, role, intent, outcome, score, body, artifacts, "
            " created_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                delta.run_id,
                delta.task_id,
                delta.employee_id,
                delta.scope,
                delta.role,
                delta.intent,
                delta.outcome,
                delta.score,
                delta.body,
                json.dumps(list(delta.artifacts)),
                delta.created_at.isoformat(),
                recorded,
            ),
        )
        if cur.rowcount == 0:  # run_id already present — first write wins, forever
            return
        self._conn.executemany(
            "INSERT OR IGNORE INTO record_file (run_id, path) VALUES (?, ?)",
            [(delta.run_id, path) for path in delta.files_touched],
        )
        self._conn.execute(
            "INSERT INTO record_fts (run_id, intent, body) VALUES (?, ?, ?)",
            (delta.run_id, delta.intent, delta.body),
        )
        self._conn.commit()

    def get(self, run_id: str) -> SprintDelta | None:
        """The record for ``run_id``, or ``None`` if absent."""
        row = self._conn.execute(
            "SELECT * FROM episodic_record WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self._to_delta(row) if row is not None else None

    def records_for(self, employee_id: str) -> list[SprintDelta]:
        """Every record for one agent, newest first — the per-agent episodic stream."""
        rows = self._conn.execute(
            "SELECT * FROM episodic_record WHERE employee_id = ? ORDER BY recorded_at DESC",
            (employee_id,),
        ).fetchall()
        return [self._to_delta(row) for row in rows]

    def records_touching(self, paths: tuple[str, ...]) -> list[SprintDelta]:
        """Records whose fingerprint overlaps any of ``paths`` — the structural pre-filter."""
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        rows = self._conn.execute(
            "SELECT r.* FROM episodic_record r "
            "WHERE r.run_id IN (SELECT run_id FROM record_file WHERE path IN "
            f"({placeholders})) ORDER BY r.recorded_at DESC",
            paths,
        ).fetchall()
        return [self._to_delta(row) for row in rows]

    def count(self) -> int:
        """Total records held."""
        return int(self._conn.execute("SELECT COUNT(*) FROM episodic_record").fetchone()[0])

    def close(self) -> None:
        self._conn.close()

    def _files_for(self, run_id: str) -> tuple[str, ...]:
        rows = self._conn.execute(
            "SELECT path FROM record_file WHERE run_id = ? ORDER BY path", (run_id,)
        ).fetchall()
        return tuple(row["path"] for row in rows)

    def _to_delta(self, row: sqlite3.Row) -> SprintDelta:
        return SprintDelta(
            run_id=row["run_id"],
            task_id=row["task_id"],
            employee_id=row["employee_id"],
            scope=row["scope"],
            intent=row["intent"],
            outcome=row["outcome"],
            score=row["score"],
            created_at=datetime.fromisoformat(row["created_at"]),
            role=row["role"],
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            artifacts=tuple(json.loads(row["artifacts"])),
            files_touched=self._files_for(row["run_id"]),
            body=row["body"],
        )


__all__ = ["EpisodicStore", "SprintDelta"]
