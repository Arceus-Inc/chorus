"""``SkillStore`` — Chorus-owned procedural memory (skills.db under company skills dir).

Mirrors :class:`~chorus.memory.EpisodicStore`: open path, migrate, expose repos.
Versioning mirrors ``routine_revision`` / Paperclip ``company_skill_versions``.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

from chorus.ids import mint_id
from chorus.ledger._migrations import MigrationRunner
from chorus.skills._models import Skill, SkillOrigin, SkillRevision, SkillState
from chorus.skills.migrations import MIGRATIONS
from chorus.skills.repos import SkillRepo, SkillRevisionRepo

_DB_NAME = "skills.db"


class SkillConflictError(RuntimeError):
    """Slug already exists for this employee."""


class SkillStore:
    """Append-only skill HEAD + revision history for one company."""

    def __init__(self, skills_dir: str | Path) -> None:
        root = Path(skills_dir)
        root.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(root / _DB_NAME)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        MigrationRunner(MIGRATIONS).apply(self._conn)
        self._skills = SkillRepo(self._conn)
        self._revisions = SkillRevisionRepo(self._conn)

    def create(
        self,
        *,
        employee_id: str,
        slug: str,
        name: str,
        description: str,
        when_to_use: str,
        file_inventory: list[dict[str, Any]],
        origin: SkillOrigin,
        action: str,
        canonical_slug: str | None = None,
        label: str | None = None,
        source_run_ids: list[str] | tuple[str, ...] = (),
        author_run_id: str | None = None,
    ) -> tuple[Skill, SkillRevision]:
        if self._skills.get_by_slug(employee_id, slug) is not None:
            raise SkillConflictError(f"skill slug already exists: {employee_id}/{slug}")

        skill_id = mint_id("skill")
        rev_id = mint_id("srev")
        inventory_json = _dumps_inventory(file_inventory)
        content_hash = _hash_inventory(inventory_json)

        skill = self._skills.insert(
            Skill(
                id=skill_id,
                employee_id=employee_id,
                slug=slug,
                name=name,
                description=description,
                when_to_use=when_to_use,
                origin=origin,
                canonical_slug=canonical_slug,
                latest_revision_id=None,
                latest_revision_no=0,
                state=SkillState.ACTIVE,
            )
        )
        rev = self._revisions.append(
            SkillRevision(
                id=rev_id,
                skill_id=skill_id,
                revision_no=1,
                action=action,
                file_inventory=inventory_json,
                content_hash=content_hash,
                label=label,
                source_run_ids=tuple(source_run_ids),
                author_run_id=author_run_id,
            )
        )
        skill = self._skills.set_head(skill_id, revision_id=rev.id, revision_no=1, bump_patch=False)
        return skill, rev

    def append_revision(
        self,
        *,
        skill_id: str,
        file_inventory: list[dict[str, Any]],
        action: str,
        label: str | None = None,
        source_run_ids: list[str] | tuple[str, ...] = (),
        author_run_id: str | None = None,
        restored_from_revision_id: str | None = None,
    ) -> SkillRevision:
        skill = self._skills.get(skill_id)
        if skill is None:
            raise KeyError(f"unknown skill_id: {skill_id}")
        next_no = skill.latest_revision_no + 1
        inventory_json = _dumps_inventory(file_inventory)
        rev = self._revisions.append(
            SkillRevision(
                id=mint_id("srev"),
                skill_id=skill_id,
                revision_no=next_no,
                action=action,
                file_inventory=inventory_json,
                content_hash=_hash_inventory(inventory_json),
                label=label,
                source_run_ids=tuple(source_run_ids),
                author_run_id=author_run_id,
                restored_from_revision_id=restored_from_revision_id,
            )
        )
        bump = action in {"patch", "write_file", "remove_file", "restore"}
        self._skills.set_head(skill_id, revision_id=rev.id, revision_no=next_no, bump_patch=bump)
        return rev

    def restore(
        self,
        *,
        skill_id: str,
        from_revision_id: str,
        label: str | None = None,
    ) -> SkillRevision:
        source = self._revisions.get(from_revision_id)
        if source is None or source.skill_id != skill_id:
            raise KeyError(f"revision not found for skill: {from_revision_id}")
        return self.append_revision(
            skill_id=skill_id,
            file_inventory=source.inventory(),
            action="restore",
            label=label or f"restore from r{source.revision_no}",
            restored_from_revision_id=from_revision_id,
        )

    def get(self, skill_id: str) -> Skill | None:
        return self._skills.get(skill_id)

    def get_by_slug(self, employee_id: str, slug: str) -> Skill | None:
        return self._skills.get_by_slug(employee_id, slug)

    def head(self, skill_id: str) -> SkillRevision | None:
        return self._revisions.head(skill_id)

    def get_revision(self, revision_id: str) -> SkillRevision | None:
        return self._revisions.get(revision_id)

    def revisions(self, skill_id: str) -> list[SkillRevision]:
        return self._revisions.by_skill(skill_id)

    def list_active(self, employee_id: str) -> list[Skill]:
        return self._skills.list_active(employee_id)

    def set_state(self, skill_id: str, state: SkillState) -> Skill:
        return self._skills.set_state(skill_id, state)

    def resolve_inventory(self, employee_id: str, slug: str) -> SkillRevision | None:
        """Live HEAD for the slug, or None when unknown."""
        skill = self._skills.get_by_slug(employee_id, slug)
        if skill is None:
            return None
        return self._revisions.head(skill.id)

    def close(self) -> None:
        self._conn.close()


def _dumps_inventory(file_inventory: list[dict[str, Any]]) -> str:
    return json.dumps(file_inventory, separators=(",", ":"), sort_keys=True)


def _hash_inventory(inventory_json: str) -> str:
    return hashlib.sha256(inventory_json.encode("utf-8")).hexdigest()


__all__ = ["SkillConflictError", "SkillStore"]
