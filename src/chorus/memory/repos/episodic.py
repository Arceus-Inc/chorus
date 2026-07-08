"""EpisodicRepo — append + read the ``episodic_record`` / ``record_fts`` rows.

Data access only (spec 01 Arceus-style per-aggregate repos); mirrors ``chorus.ledger.repos.RunRepo``.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger.repos._base import dumps, loads, to_iso
from chorus.memory._models import SprintDelta
from chorus.memory._narrative import narrative


class EpisodicRepo:
    """Append-only access to one beat's episodic record + FTS5 search index."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only, spec 07 §3)."""
        recorded = to_iso(delta.recorded_at or delta.created_at)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO episodic_record "
            "(run_id, task_id, employee_id, scope, role, intent, outcome, score, body, artifacts, "
            " files_touched, created_at, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                dumps(list(delta.files_touched)),
                to_iso(delta.created_at),
                recorded,
            ),
        )
        if cur.rowcount == 0:  # run_id already present — first write wins, forever
            return
        self._conn.execute(
            "INSERT INTO record_fts (run_id, intent, body) VALUES (?, ?, ?)",
            (delta.run_id, delta.intent, narrative(delta.body)),
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

    def search(self, query: str, *, limit: int = 5) -> list[SprintDelta]:
        """Keyword search over intent+body, best match first — the BM25 half of retrieval.

        FTS5's ``bm25()`` is more-negative-is-better, so ``ORDER BY bm25(record_fts)`` ascending is
        best-first. Each term is quoted as an FTS5 string literal (its own internal ``"`` doubled) and
        OR-joined, so arbitrary free text — including FTS5 operator characters like ``-``/``*``/``:``
        — can never be mis-parsed as query syntax.
        """
        match = _fts_or_query(query)
        if not match:
            return []
        rows = self._conn.execute(
            "SELECT r.* FROM episodic_record r "
            "JOIN record_fts f ON f.run_id = r.run_id "
            "WHERE record_fts MATCH ? ORDER BY bm25(record_fts) LIMIT ?",
            (match, limit),
        ).fetchall()
        return [self._to_delta(row) for row in rows]

    def count(self) -> int:
        """Total records held."""
        return int(self._conn.execute("SELECT COUNT(*) FROM episodic_record").fetchone()[0])

    def _to_delta(self, row: sqlite3.Row) -> SprintDelta:
        raw_files = loads(row["files_touched"]) if row["files_touched"] else []
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
            files_touched=tuple(raw_files or []),
            body=row["body"],
        )


def _fts_or_query(query: str) -> str:
    """Turn free text into a safe FTS5 ``MATCH`` expression: quoted terms, OR-joined.

    Quoting each term as an FTS5 string literal (doubling any internal ``"``) means operator
    characters in the raw query (``-``, ``*``, ``:``, …) are always literal text, never query syntax —
    the search is never a way to inject a broken or unintended FTS5 query.
    """
    terms = query.split()
    quoted = (f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)
    return " OR ".join(quoted)


__all__ = ["EpisodicRepo"]
