"""Skill pin repo — optional historical revision binding."""

from __future__ import annotations

import sqlite3

from chorus.ledger.repos._base import from_iso, utcnow_iso
from chorus.skills._models import SkillPin


class SkillPinRepo:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def set(self, employee_id: str, slug: str, revision_id: str | None) -> SkillPin:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO skill_pin (employee_id, slug, revision_id, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(employee_id, slug) DO UPDATE SET "
            "revision_id = excluded.revision_id, updated_at = excluded.updated_at",
            (employee_id, slug, revision_id, now),
        )
        self._conn.commit()
        return SkillPin(
            employee_id=employee_id,
            slug=slug,
            revision_id=revision_id,
            updated_at=from_iso(now),
        )

    def get(self, employee_id: str, slug: str) -> SkillPin | None:
        row = self._conn.execute(
            "SELECT * FROM skill_pin WHERE employee_id = ? AND slug = ?",
            (employee_id, slug),
        ).fetchone()
        if row is None:
            return None
        return SkillPin(
            employee_id=row["employee_id"],
            slug=row["slug"],
            revision_id=row["revision_id"],
            updated_at=from_iso(row["updated_at"]),
        )
