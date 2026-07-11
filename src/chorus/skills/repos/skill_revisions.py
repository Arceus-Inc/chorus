"""SkillRevisionRepo — append-only skill package snapshots."""

from __future__ import annotations

import sqlite3

from chorus.ledger.repos._base import dumps, from_iso, loads, require_persisted, utcnow_iso
from chorus.skills._models import SkillRevision


class SkillRevisionRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def append(self, revision: SkillRevision) -> SkillRevision:
        self._conn.execute(
            "INSERT INTO skill_revision ("
            "id, skill_id, revision_no, label, action, file_inventory, content_hash, "
            "source_run_ids, author_run_id, restored_from_revision_id, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                revision.id,
                revision.skill_id,
                revision.revision_no,
                revision.label,
                revision.action,
                revision.file_inventory,
                revision.content_hash,
                dumps(list(revision.source_run_ids)),
                revision.author_run_id,
                revision.restored_from_revision_id,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(revision.id), revision.id)

    def get(self, revision_id: str) -> SkillRevision | None:
        row = self._conn.execute(
            "SELECT * FROM skill_revision WHERE id = ?", (revision_id,)
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def head(self, skill_id: str) -> SkillRevision | None:
        row = self._conn.execute(
            "SELECT * FROM skill_revision WHERE skill_id = ? "
            "ORDER BY revision_no DESC LIMIT 1",
            (skill_id,),
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def by_skill(self, skill_id: str) -> list[SkillRevision]:
        rows = self._conn.execute(
            "SELECT * FROM skill_revision WHERE skill_id = ? ORDER BY revision_no",
            (skill_id,),
        ).fetchall()
        return [_row_to_revision(r) for r in rows]


def _row_to_revision(row: sqlite3.Row) -> SkillRevision:
    raw_ids = loads(row["source_run_ids"]) or []
    return SkillRevision(
        id=row["id"],
        skill_id=row["skill_id"],
        revision_no=int(row["revision_no"]),
        action=row["action"],
        file_inventory=row["file_inventory"],
        content_hash=row["content_hash"],
        label=row["label"],
        source_run_ids=tuple(str(x) for x in raw_ids),
        author_run_id=row["author_run_id"],
        restored_from_revision_id=row["restored_from_revision_id"],
        created_at=from_iso(row["created_at"]),
    )
