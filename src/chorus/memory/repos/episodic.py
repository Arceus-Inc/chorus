"""EpisodicRepo — bounded reads, retention metadata, and tsvector search (R0 + R2)."""

from __future__ import annotations

from datetime import datetime

from chorus.ledger.repos._base import LedgerConnection, LedgerRow, dumps, loads, to_iso
from chorus.memory.episodic.models import SprintDelta
from chorus.memory.episodic.narrative import narrative, normalize_for_fts
from chorus.memory.episodic.recall_filters import EpisodicQueryFilters, filter_clause
from chorus.memory.episodic.search_hit import EpisodicSearchHit

_HOT_TIER = "hot"
_MAX_QUERY_CHARS = 2_048
_TSV = "to_tsvector('simple', search_text)"
_HEADLINE_OPTS = "StartSel=>>>, StopSel=<<<, MaxWords=40, MinWords=20"


class EpisodicRepo:
    """Append-only episodic records + tsvector search; retention columns are mutable metadata only."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def append(self, delta: SprintDelta) -> None:
        """Append one raw episodic record; a repeated ``run_id`` is a no-op (append-only, spec 07 §3)."""
        recorded = to_iso(delta.recorded_at or delta.created_at)
        search_text = (
            normalize_for_fts(delta.intent) + "\n" + normalize_for_fts(narrative(delta.body))
        )
        self._conn.execute(
            "INSERT INTO episodic_record "
            "(run_id, task_id, employee_id, scope, role, intent, outcome, score, body, artifacts, "
            " files_touched, created_at, recorded_at, pin_count, last_recalled_at, tier, "
            " search_text) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT (run_id) DO NOTHING",
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
                search_text,
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
    ) -> list[EpisodicSearchHit]:
        """Keyword search over intent+body; each hit carries a ``ts_headline`` match snippet.

        ``websearch_to_tsquery`` parses free text safely (implicit AND, quoted phrases) — the
        FTS5 sanitizer this replaces is unnecessary on Postgres.
        """
        if not query or not query.strip():
            return []
        match = query.strip()[:_MAX_QUERY_CHARS]
        sql = (
            "SELECT r.*, "
            f"ts_headline('simple', r.search_text, websearch_to_tsquery('simple', ?), "
            f"'{_HEADLINE_OPTS}') AS snip "
            "FROM episodic_record r "
            f"WHERE {_TSV.replace('search_text', 'r.search_text')} "
            "      @@ websearch_to_tsquery('simple', ?) "
            "AND r.tier = ?"
        )
        params: list[object] = [match, match, tier]
        if employee_id is not None:
            sql += " AND r.employee_id = ?"
            params.append(employee_id)
        extra_sql, extra_params = filter_clause(filters, alias="r")
        sql += extra_sql
        params.extend(extra_params)
        sql += (
            f" ORDER BY ts_rank({_TSV.replace('search_text', 'r.search_text')}, "
            "websearch_to_tsquery('simple', ?)) DESC LIMIT ?"
        )
        params.extend([match, limit])
        rows = self._conn.execute(sql, params).fetchall()
        return [
            EpisodicSearchHit(
                record=self._to_delta(row),
                snippet=(row["snip"] or "").strip(),
            )
            for row in rows
        ]

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
        row = self._conn.execute("SELECT COUNT(*) AS n FROM episodic_record").fetchone()
        return int(row["n"])

    def _to_delta(self, row: LedgerRow) -> SprintDelta:
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
