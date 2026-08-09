"""Procedural skill row models — skill HEAD + immutable revisions (Paperclip lineage).

Live in the shared engine schema (``0002_skills`` migration): company_id + FORCE RLS like every
ledger table. The domain logic (SkillManager, patches) stays in ``chorus.skills``."""

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
    patch_count: int = 0
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
class EvalCase:
    """One reusable evaluation pinned to an immutable skill revision."""

    id: str
    skill_revision_id: str
    name: str
    input_text: str
    expected_behavior: str
    created_at: datetime | None = None


__all__ = [
    "EvalCase",
    "Skill",
    "SkillOrigin",
    "SkillRevision",
    "SkillState",
]
