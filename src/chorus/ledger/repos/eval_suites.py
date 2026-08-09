"""EvalSuiteRepo — ordered eval cases pinned to immutable skill revisions."""

from __future__ import annotations

from chorus.ledger._models import EvalSuite
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class EvalSuiteRepo:
    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def create(self, suite: EvalSuite) -> EvalSuite:
        try:
            self._conn.execute(
                "INSERT INTO eval_suite (id, skill_revision_id, created_at) VALUES (?, ?, ?)",
                (suite.id, suite.skill_revision_id, utcnow_iso()),
            )
            for position, case_id in enumerate(suite.case_ids):
                self._conn.execute(
                    "INSERT INTO eval_suite_case (suite_id, skill_revision_id, case_id, position) "
                    "VALUES (?, ?, ?, ?)",
                    (suite.id, suite.skill_revision_id, case_id, position),
                )
        except Exception:
            self._conn.rollback()
            raise
        self._conn.commit()
        return require_persisted(self.get(suite.id), suite.id)

    def get(self, suite_id: str) -> EvalSuite | None:
        row = self._conn.execute("SELECT * FROM eval_suite WHERE id = ?", (suite_id,)).fetchone()
        if row is None:
            return None
        case_rows = self._conn.execute(
            "SELECT case_id FROM eval_suite_case WHERE suite_id = ? ORDER BY position", (suite_id,)
        ).fetchall()
        return _row_to_eval_suite(row, tuple(case_row["case_id"] for case_row in case_rows))

    def by_skill_revision(self, skill_revision_id: str) -> list[EvalSuite]:
        rows = self._conn.execute(
            "SELECT id FROM eval_suite WHERE skill_revision_id = ? ORDER BY created_at, id",
            (skill_revision_id,),
        ).fetchall()
        return [require_persisted(self.get(row["id"]), row["id"]) for row in rows]


def _row_to_eval_suite(row: LedgerRow, case_ids: tuple[str, ...]) -> EvalSuite:
    return EvalSuite(
        id=row["id"],
        skill_revision_id=row["skill_revision_id"],
        case_ids=case_ids,
        created_at=from_iso(row["created_at"]),
    )
