"""The Backend Engineer's brief must carry a craft bar (§08/§09): structure + clean code + a gate.

Bex's early services shipped as a flat pile of scripts with broad `except Exception`s and no lint/type
gate — green tests but poor code. The brief now demands a proper package layout, clean idiomatic code,
and a MECHANICAL quality gate (formatter/linter/type-checker over its own code, recorded as
test_evidence). These tests pin that intent so it can't silently regress.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus_employee.backend_engineer import BACKEND_ENGINEER_BRIEF, backend_engineer_plugin

pytestmark = pytest.mark.unit


class TestQualityGateWiring:
    def test_manifest_grants_the_code_quality_tool_and_skill_loader(self) -> None:
        tools = set(backend_engineer_plugin().manifest.tools)
        assert "code_quality" in tools
        assert "skill" in tools

    def test_manifest_carries_the_framework_agnostic_quality_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "verifying-any-stack" in manifest.skills
        assert manifest.skills_root is not None

    def test_the_verifying_any_stack_skill_file_exists(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "verifying-any-stack" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "code_quality" in body  # points at the tool
        assert "discover" in body  # framework-agnostic discovery, not a hardcoded table

    def test_brief_routes_the_quality_gate_through_the_tool_and_skill(self) -> None:
        brief = BACKEND_ENGINEER_BRIEF
        assert "code_quality" in brief
        assert "verifying-any-stack" in brief

    def test_brief_demands_all_three_quality_kinds_not_just_types(self) -> None:
        # The mechanical lever: format + lint + types are non-optional, tagged by kind.
        brief = BACKEND_ENGINEER_BRIEF
        assert "ALL THREE" in brief
        assert '"kind"' in brief  # each check is tagged with its gate kind


class TestStructureSkillWiring:
    def test_manifest_carries_the_structuring_skill(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert "structuring-any-service" in manifest.skills
        assert manifest.skills_root is not None

    def test_the_structuring_skill_file_exists(self) -> None:
        manifest = backend_engineer_plugin().manifest
        assert manifest.skills_root is not None
        skill = Path(manifest.skills_root) / "structuring-any-service" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8").lower()
        assert "by domain" in body  # the #1 rule
        assert "inward" in body  # dependency direction

    def test_brief_routes_structure_through_the_skill_and_demands_by_domain(self) -> None:
        brief = BACKEND_ENGINEER_BRIEF
        assert "structuring-any-service" in brief
        assert "DOMAIN" in brief
        assert "INWARD" in brief


def test_brief_demands_a_package_layout_not_a_flat_dump() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "package" in brief
    assert "flat" in brief  # "never a flat pile of scripts"


def test_brief_demands_layered_separation_of_concerns() -> None:
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "transport/http → service → data-access → domain" in brief
    assert "one reason to change" in brief


def test_brief_forbids_broad_exceptions_and_wants_full_typing() -> None:
    brief = BACKEND_ENGINEER_BRIEF
    assert "except Exception" in brief  # named as the thing NOT to do
    assert "type every function signature" in BACKEND_ENGINEER_BRIEF.lower()


def test_brief_requires_a_mechanical_lint_or_type_gate() -> None:
    # "clean code" must be proven, not eyeballed — a formatter/linter/type-checker over its own code,
    # recorded as a test_evidence gate.
    brief = BACKEND_ENGINEER_BRIEF.lower()
    assert "linter" in brief or "ruff" in brief
    assert "test_evidence" in brief
    assert "red gate" in brief


def test_brief_keeps_the_landed_diff_clean_of_scratch_files() -> None:
    assert "no scratch" in BACKEND_ENGINEER_BRIEF.lower()


def test_brief_has_the_resume_reconcile_directive() -> None:
    # The cross-beat resumption protocol: keep a durable TODO.md via todo_write, read it FIRST and
    # reconcile intent (the checklist) against reality (git + tests), resume rather than restart.
    brief = BACKEND_ENGINEER_BRIEF
    assert "todo_write" in brief
    assert "TODO.md" in brief
    assert "resume" in brief.lower()
    assert "reconcile" in brief.lower()
