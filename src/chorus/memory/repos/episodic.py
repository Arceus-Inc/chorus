"""EpisodicRepo — append + read the ``episodic_record`` / ``record_file`` / ``record_fts`` rows.

Data access only (spec 01 Arceus-style per-aggregate repos); mirrors ``chorus.ledger.repos.RunRepo``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger.repos._base import dumps, loads, to_iso
from chorus.memory._models import SprintDelta


class EpisodicRepo:
    """Append-only access to one beat's episodic record + its fingerprint fan-out + FTS5 index."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only, spec 07 §3)."""
        recorded = to_iso(delta.recorded_at or delta.created_at)
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
                dumps(list(delta.artifacts)),
                to_iso(delta.created_at),
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

    def for_employee(self, employee_id: str) -> list[SprintDelta]:
        """Every record for one agent, newest first — the per-agent episodic stream."""
        rows = self._conn.execute(
            "SELECT * FROM episodic_record WHERE employee_id = ? ORDER BY recorded_at DESC",
            (employee_id,),
        ).fetchall()
        return [self._to_delta(row) for row in rows]

    def touching(self, paths: tuple[str, ...]) -> list[SprintDelta]:
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
            artifacts=tuple(loads(row["artifacts"]) or []),
            files_touched=self._files_for(row["run_id"]),
            body=row["body"],
        )


__all__ = ["EpisodicRepo"]
