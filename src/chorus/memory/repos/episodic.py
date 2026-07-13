"""EpisodicRepo — bounded reads, retention metadata, and FTS search (R0 + R2)."""

from __future__ import annotations

import sqlite3
from datetime import datetime

from chorus.ledger.repos._base import dumps, loads, to_iso
from chorus.memory.episodic.fts_query import sanitize_fts5_query
from chorus.memory.episodic.models import SprintDelta
from chorus.memory.episodic.narrative import narrative, normalize_for_fts
from chorus.memory.episodic.recall_filters import EpisodicQueryFilters, filter_clause

_HOT_TIER = "hot"


class EpisodicRepo:
    """Append-only episodic records + FTS5 search; retention columns are mutable metadata only."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only, spec 07 §3)."""
        recorded = to_iso(delta.recorded_at or delta.created_at)
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO episodic_record "
            "(run_id, task_id, employee_id, scope, role, intent, outcome, score, body, artifacts, "
            " files_touched, created_at, recorded_at, pin_count, last_recalled_at, tier) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                delta.pin_count,
                to_iso(delta.last_recalled_at) if delta.last_recalled_at else None,
                delta.tier,
            ),
        )
        if cur.rowcount == 0:
            return
        self._conn.execute(
            "INSERT INTO record_fts (run_id, intent, body) VALUES (?, ?, ?)",
            (
                delta.run_id,
                normalize_for_fts(delta.intent),
                normalize_for_fts(narrative(delta.body)),
            ),
        )
        self._conn.commit()

    def get(self, run_id: str) -> SprintDelta | None:
        """The record for ``run_id``, or ``None`` if absent."""
        row = self._conn.execute(
            "SELECT * FROM episodic_record WHERE run_id = ?", (run_id,)
        ).fetchone()
        return self._to_delta(row) if row is not None else None

    def for_employee(
        self,
        employee_id: str,
        *,
        limit: int | None = None,
        tier: str = _HOT_TIER,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[SprintDelta]:
        """Hot-tier records for one agent, newest first — bounded when ``limit`` is set."""
        sql = "SELECT * FROM episodic_record WHERE employee_id = ? AND tier = ? "
        params: list[object] = [employee_id, tier]
        extra_sql, extra_params = filter_clause(filters)
        sql += extra_sql
        params.extend(extra_params)
        sql += " ORDER BY recorded_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._to_delta(row) for row in rows]

    def search(
        self,
        query: str,
        *,
        employee_id: str | None = None,
        limit: int = 5,
        tier: str = _HOT_TIER,
        filters: EpisodicQueryFilters | None = None,
    ) -> list[SprintDelta]:
        """Keyword search over intent+body; optionally scoped to one employee's hot tier."""
        match = sanitize_fts5_query(query)
        if not match:
            return []
        sql = (
            "SELECT r.* FROM episodic_record r "
            "JOIN record_fts f ON f.run_id = r.run_id "
            "WHERE record_fts MATCH ? AND r.tier = ?"
        )
        params: list[object] = [match, tier]
        if employee_id is not None:
            sql += " AND r.employee_id = ?"
            params.append(employee_id)
        extra_sql, extra_params = filter_clause(filters, alias="r")
        sql += extra_sql
        params.extend(extra_params)
        sql += " ORDER BY bm25(record_fts) LIMIT ?"
        params.append(limit)
        try:
            rows = self._conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            # Bad FTS5 syntax despite sanitize — empty result, never raise to the agent.
            return []
        return [self._to_delta(row) for row in rows]

    def touch_recalled(self, run_ids: tuple[str, ...], *, now: datetime) -> None:
        """Best-effort reinforcement — updates ``last_recalled_at`` for returned hits."""
        if not run_ids:
            return
        placeholders = ", ".join("?" for _ in run_ids)
        self._conn.execute(
            f"UPDATE episodic_record SET last_recalled_at = ? WHERE run_id IN ({placeholders})",
            (to_iso(now), *run_ids),
        )
        self._conn.commit()

    def pin_run_ids(self, employee_id: str, run_ids: tuple[str, ...]) -> None:
        """Increment pin count for cited episodic rows (lattice apply seam)."""
        if not run_ids:
            return
        placeholders = ", ".join("?" for _ in run_ids)
        self._conn.execute(
            f"UPDATE episodic_record SET pin_count = pin_count + 1 "
            f"WHERE employee_id = ? AND run_id IN ({placeholders})",
            (employee_id, *run_ids),
        )
        self._conn.commit()

    def count(self) -> int:
        """Total records held."""
        return int(self._conn.execute("SELECT COUNT(*) FROM episodic_record").fetchone()[0])

    def _to_delta(self, row: sqlite3.Row) -> SprintDelta:
        raw_files = loads(row["files_touched"]) if row["files_touched"] else []
        last_recalled_raw = row["last_recalled_at"]
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
            pin_count=int(row["pin_count"]),
            last_recalled_at=(
                datetime.fromisoformat(last_recalled_raw) if last_recalled_raw else None
            ),
            tier=str(row["tier"]),
        )


__all__ = ["EpisodicRepo"]
