"""Procedural skill row models — Chorus-owned (Paperclip company_skills + routine_revision)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any


class SkillOrigin(StrEnum):
    """Where the skill came from."""

    CANONICAL = "canonical"  # mirrored from role package (rare)
    EVOLVED = "evolved"  # patched umbrella over a role skill
    CREATED = "created"  # new class-level playbook


class SkillState(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"


@dataclass(frozen=True)
class Skill:
    """HEAD registry row — points at latest ``skill_revision``."""

    id: str
    employee_id: str
    slug: str
    name: str
    description: str = ""
    when_to_use: str = ""
    origin: SkillOrigin = SkillOrigin.CREATED
    canonical_slug: str | None = None
    latest_revision_id: str | None = None
    latest_revision_no: int = 0
    state: SkillState = SkillState.ACTIVE
    created_by: str | None = None
    curation_eligible: bool = False
    use_count: int = 0
    view_count: int = 0
    patch_count: int = 0
    last_used_at: datetime | None = None
    last_patched_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class SkillRevision:
    """One immutable full-file snapshot of a skill package."""

    id: str
    skill_id: str
    revision_no: int
    action: str
    file_inventory: str  # JSON text
    content_hash: str
    label: str | None = None
    source_run_ids: tuple[str, ...] = ()
    author_run_id: str | None = None
    restored_from_revision_id: str | None = None
    created_at: datetime | None = None

    def inventory(self) -> list[dict[str, Any]]:
        import json

        data = json.loads(self.file_inventory)
        return list(data) if isinstance(data, list) else []


@dataclass(frozen=True)
class SkillPin:
    """Optional pin: ``revision_id is None`` means live HEAD."""

    employee_id: str
    slug: str
    revision_id: str | None
    updated_at: datetime | None = None


__all__ = [
    "Skill",
    "SkillOrigin",
    "SkillPin",
    "SkillRevision",
    "SkillState",
]
