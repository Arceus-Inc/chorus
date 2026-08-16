"""EvalCaseRepo — reusable cases pinned to immutable skill revisions."""

from __future__ import annotations

from chorus.ledger._models import EvalCase
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class EvalCaseRepo:
    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, case: EvalCase) -> EvalCase:
        self._conn.execute(
            "INSERT INTO eval_case ("
            "id, skill_revision_id, name, input_text, expected_behavior, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                case.id,
                case.skill_revision_id,
                case.name,
                case.input_text,
                case.expected_behavior,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(case.id), case.id)

    def get(self, case_id: str) -> EvalCase | None:
        row = self._conn.execute("SELECT * FROM eval_case WHERE id = ?", (case_id,)).fetchone()
        return _row_to_eval_case(row) if row is not None else None

    def by_skill_revision(self, skill_revision_id: str) -> list[EvalCase]:
        rows = self._conn.execute(
            "SELECT * FROM eval_case WHERE skill_revision_id = ? ORDER BY name", (skill_revision_id,)
        ).fetchall()
        return [_row_to_eval_case(row) for row in rows]


def _row_to_eval_case(row: LedgerRow) -> EvalCase:
    return EvalCase(
        id=row["id"],
        skill_revision_id=row["skill_revision_id"],
        name=row["name"],
        input_text=row["input_text"],
        expected_behavior=row["expected_behavior"],
        created_at=from_iso(row["created_at"]),
    )
