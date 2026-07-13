"""SkillRepo — HEAD registry for employee-scoped procedural skills."""

from __future__ import annotations

import sqlite3

from chorus.ledger.repos._base import from_iso, require_persisted, utcnow_iso
from chorus.skills._models import Skill, SkillOrigin, SkillState


class SkillRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert(self, skill: Skill) -> Skill:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO skill ("
            "id, employee_id, slug, name, description, when_to_use, origin, canonical_slug, "
            "latest_revision_id, latest_revision_no, state, patch_count, last_patched_at, "
            "created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                skill.id,
                skill.employee_id,
                skill.slug,
                skill.name,
                skill.description,
                skill.when_to_use,
                skill.origin.value,
                skill.canonical_slug,
                skill.latest_revision_id,
                skill.latest_revision_no,
                skill.state.value,
                skill.patch_count,
                None,
                now,
                now,
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(skill.id), skill.id)

    def get(self, skill_id: str) -> Skill | None:
        row = self._conn.execute("SELECT * FROM skill WHERE id = ?", (skill_id,)).fetchone()
        return _row_to_skill(row) if row is not None else None

    def get_by_slug(self, employee_id: str, slug: str) -> Skill | None:
        row = self._conn.execute(
            "SELECT * FROM skill WHERE employee_id = ? AND slug = ?",
            (employee_id, slug),
        ).fetchone()
        return _row_to_skill(row) if row is not None else None

    def list_active(self, employee_id: str) -> list[Skill]:
        rows = self._conn.execute(
            "SELECT * FROM skill WHERE employee_id = ? AND state = ? ORDER BY slug",
            (employee_id, SkillState.ACTIVE.value),
        ).fetchall()
        return [_row_to_skill(r) for r in rows]

    def set_head(
        self, skill_id: str, *, revision_id: str, revision_no: int, bump_patch: bool
    ) -> Skill:
        now = utcnow_iso()
        if bump_patch:
            self._conn.execute(
                "UPDATE skill SET latest_revision_id = ?, latest_revision_no = ?, "
                "patch_count = patch_count + 1, last_patched_at = ?, updated_at = ? WHERE id = ?",
                (revision_id, revision_no, now, now, skill_id),
            )
        else:
            self._conn.execute(
                "UPDATE skill SET latest_revision_id = ?, latest_revision_no = ?, updated_at = ? "
                "WHERE id = ?",
                (revision_id, revision_no, now, skill_id),
            )
        self._conn.commit()
        return require_persisted(self.get(skill_id), skill_id)

    def set_state(self, skill_id: str, state: SkillState) -> Skill:
        now = utcnow_iso()
        self._conn.execute(
            "UPDATE skill SET state = ?, updated_at = ? WHERE id = ?",
            (state.value, now, skill_id),
        )
        self._conn.commit()
        return require_persisted(self.get(skill_id), skill_id)


def _row_to_skill(row: sqlite3.Row) -> Skill:
    return Skill(
        id=row["id"],
        employee_id=row["employee_id"],
        slug=row["slug"],
        name=row["name"],
        description=row["description"] or "",
        when_to_use=row["when_to_use"] or "",
        origin=SkillOrigin(row["origin"]),
        canonical_slug=row["canonical_slug"],
        latest_revision_id=row["latest_revision_id"],
        latest_revision_no=int(row["latest_revision_no"] or 0),
        state=SkillState(row["state"]),
        patch_count=int(row["patch_count"] or 0),
        last_patched_at=from_iso(row["last_patched_at"]),
        created_at=from_iso(row["created_at"]),
        updated_at=from_iso(row["updated_at"]),
    )
