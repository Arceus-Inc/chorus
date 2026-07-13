"""Skill + skill_revision repos — append-only procedural memory (Paperclip / routine_revision).

SoT lives in Chorus at ``{company_root}/skills/skills.db``, not Lattice.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chorus.skills import SkillOrigin, SkillState, SkillStore

pytestmark = pytest.mark.unit


def _store(tmp_path: Path) -> SkillStore:
    return SkillStore(tmp_path / "skills")


def test_create_skill_writes_revision_one(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        skill, rev = store.create(
            employee_id="bex",
            slug="structuring-any-service",
            name="Structuring Any Service",
            description="How to structure a service",
            when_to_use="before writing a service",
            file_inventory=[
                {
                    "path": "SKILL.md",
                    "kind": "file",
                    "content": "---\nname: structuring-any-service\n"
                    'description: "How to structure a service"\n'
                    'when_to_use: "before writing a service"\n'
                    "---\n\n# Structuring\n\nBody.\n",
                }
            ],
            origin=SkillOrigin.EVOLVED,
            canonical_slug="structuring-any-service",
            action="create",
            label="Initial",
        )
        assert skill.slug == "structuring-any-service"
        assert skill.latest_revision_id == rev.id
        assert skill.latest_revision_no == 1
        assert rev.revision_no == 1
        assert rev.action == "create"
        assert json.loads(rev.file_inventory)[0]["path"] == "SKILL.md"
        assert rev.content_hash
    finally:
        store.close()


def test_append_revision_advances_head(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        skill, _ = store.create(
            employee_id="bex",
            slug="structuring-any-service",
            name="Structuring",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# v1\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        rev2 = store.append_revision(
            skill_id=skill.id,
            file_inventory=[
                {
                    "path": "SKILL.md",
                    "kind": "file",
                    "content": "# v1\n\n## Before patching HTTP clients\n\nstep\n",
                }
            ],
            action="patch",
            label="EVOLVE: Before patching HTTP clients",
            source_run_ids=["r0", "r1"],
        )
        head = store.head(skill.id)
        assert head is not None
        assert head.id == rev2.id
        assert head.revision_no == 2
        assert head.source_run_ids == ("r0", "r1")
        got = store.get(skill.id)
        assert got is not None
        assert got.latest_revision_no == 2
        assert got.patch_count == 1
    finally:
        store.close()


def test_restore_appends_new_revision_never_rewrites(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        skill, rev1 = store.create(
            employee_id="bex",
            slug="playbook",
            name="Playbook",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# original\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        store.append_revision(
            skill_id=skill.id,
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# broken\n"}],
            action="edit",
        )
        restored = store.restore(skill_id=skill.id, from_revision_id=rev1.id, label="rollback")
        assert restored.revision_no == 3
        assert restored.restored_from_revision_id == rev1.id
        assert restored.action == "restore"
        inventory = json.loads(restored.file_inventory)
        assert inventory[0]["content"] == "# original\n"
        # History intact
        assert len(store.revisions(skill.id)) == 3
        assert store.get_revision(rev1.id) is not None
    finally:
        store.close()


def test_get_by_employee_slug(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.create(
            employee_id="bex",
            slug="alpha",
            name="Alpha",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# a\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        assert store.get_by_slug("bex", "alpha") is not None
        assert store.get_by_slug("bex", "missing") is None
        assert store.get_by_slug("other", "alpha") is None
    finally:
        store.close()


def test_duplicate_slug_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.create(
            employee_id="bex",
            slug="alpha",
            name="Alpha",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# a\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        with pytest.raises(Exception):
            store.create(
                employee_id="bex",
                slug="alpha",
                name="Alpha again",
                description="d",
                when_to_use="w",
                file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# b\n"}],
                origin=SkillOrigin.CREATED,
                action="create",
            )
    finally:
        store.close()


def test_list_active_for_employee(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        store.create(
            employee_id="bex",
            slug="a",
            name="A",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# a\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        s2, _ = store.create(
            employee_id="bex",
            slug="b",
            name="B",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# b\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        store.set_state(s2.id, SkillState.ARCHIVED)
        active = store.list_active("bex")
        assert [s.slug for s in active] == ["a"]
    finally:
        store.close()


def test_pin_and_resolve_revision(tmp_path: Path) -> None:
    store = _store(tmp_path)
    try:
        skill, rev1 = store.create(
            employee_id="bex",
            slug="alpha",
            name="Alpha",
            description="d",
            when_to_use="w",
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# v1\n"}],
            origin=SkillOrigin.CREATED,
            action="create",
        )
        rev2 = store.append_revision(
            skill_id=skill.id,
            file_inventory=[{"path": "SKILL.md", "kind": "file", "content": "# v2\n"}],
            action="edit",
        )
        # No pin → HEAD
        resolved = store.resolve_inventory("bex", "alpha")
        assert resolved is not None
        assert json.loads(resolved.file_inventory)[0]["content"] == "# v2\n"
        store.set_pin("bex", "alpha", rev1.id)
        pinned = store.resolve_inventory("bex", "alpha")
        assert pinned is not None
        assert pinned.id == rev1.id
        store.set_pin("bex", "alpha", None)  # clear → HEAD
        assert store.resolve_inventory("bex", "alpha").id == rev2.id
    finally:
        store.close()
