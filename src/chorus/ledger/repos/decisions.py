"""DecisionRepo + ClaimRepo — data access for the Decision OS rows (pm design doc §10).

Pure data access: the confidence-floor policy and the atomic decision+claims write live one layer up
in :class:`~chorus.lifecycle.CapabilityService`. ``rejected_alternatives`` is stored as a JSON array
and rehydrated into :class:`~chorus.ledger._models.RejectedAlternative` tuples; ``for_decisions`` is a
single ``IN`` query so rendering a packet across many decisions never becomes N+1.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Claim, DecisionRecord, RejectedAlternative
from chorus.ledger.repos._base import dumps, from_iso, loads_list, require_persisted, utcnow_iso


class DecisionRepo:
    """Create, read, and supersede ``decision_record`` rows (data access only)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, decision: DecisionRecord) -> DecisionRecord:
        self._conn.execute(
            "INSERT INTO decision_record (id, task_id, option, rationale, confidence, "
            "outcome_metric, revisit_trigger, rejected_alternatives, superseded_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                decision.id,
                decision.task_id,
                decision.option,
                decision.rationale,
                decision.confidence,
                decision.outcome_metric,
                decision.revisit_trigger,
                dumps(
                    [
                        {"option": alt.option, "reason": alt.reason}
                        for alt in decision.rejected_alternatives
                    ]
                ),
                decision.superseded_by,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(decision.id), decision.id)

    def get(self, decision_id: str) -> DecisionRecord | None:
        row = self._conn.execute(
            "SELECT * FROM decision_record WHERE id = ?", (decision_id,)
        ).fetchone()
        return _row_to_decision(row) if row is not None else None

    def for_task(self, task_id: str) -> list[DecisionRecord]:
        rows = self._conn.execute(
            "SELECT * FROM decision_record WHERE task_id = ? ORDER BY created_at DESC, id DESC",
            (task_id,),
        ).fetchall()
        return [_row_to_decision(row) for row in rows]

    def set_superseded_by(self, decision_id: str, successor_id: str) -> None:
        """Point ``decision_id`` forward at its successor — the only mutation a record ever takes."""
        self._conn.execute(
            "UPDATE decision_record SET superseded_by = ? WHERE id = ?",
            (successor_id, decision_id),
        )
        self._conn.commit()


class ClaimRepo:
    """Create ``claim`` rows and batch-read them for a set of decisions (data access only)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, claim: Claim) -> Claim:
        self._conn.execute(
            "INSERT INTO claim (id, decision_id, text, source_url, confidence, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                claim.id,
                claim.decision_id,
                claim.text,
                claim.source_url,
                claim.confidence,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(claim.id), claim.id)

    def get(self, claim_id: str) -> Claim | None:
        row = self._conn.execute("SELECT * FROM claim WHERE id = ?", (claim_id,)).fetchone()
        return _row_to_claim(row) if row is not None else None

    def for_decisions(self, decision_ids: list[str]) -> list[Claim]:
        """Every claim under any of ``decision_ids`` — one ``IN`` query, never a per-decision loop."""
        if not decision_ids:
            return []
        placeholders = ",".join("?" for _ in decision_ids)
        rows = self._conn.execute(
            f"SELECT * FROM claim WHERE decision_id IN ({placeholders}) ORDER BY id",
            decision_ids,
        ).fetchall()
        return [_row_to_claim(row) for row in rows]


def _row_to_decision(row: sqlite3.Row) -> DecisionRecord:
    alternatives = tuple(
        RejectedAlternative(option=alt["option"], reason=alt["reason"])
        for alt in loads_list(row["rejected_alternatives"])
    )
    return DecisionRecord(
        id=row["id"],
        task_id=row["task_id"],
        option=row["option"],
        rationale=row["rationale"],
        confidence=row["confidence"],
        outcome_metric=row["outcome_metric"],
        revisit_trigger=row["revisit_trigger"],
        rejected_alternatives=alternatives,
        superseded_by=row["superseded_by"],
        created_at=from_iso(row["created_at"]),
    )


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=row["id"],
        decision_id=row["decision_id"],
        text=row["text"],
        source_url=row["source_url"],
        confidence=row["confidence"],
        created_at=from_iso(row["created_at"]),
    )


__all__ = ["ClaimRepo", "DecisionRepo"]
