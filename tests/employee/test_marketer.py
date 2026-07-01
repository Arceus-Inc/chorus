"""Marketer — Slice 0: plugin assembly, manifest shape, DoD, and lander (design doc §01-§15)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import ArtifactType, DoDKind
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, SandboxTier
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers
from chorus_employee.marketer import (
    MARKETER_BRIEF,
    MARKETER_CONTENT_DOC,
    MARKETER_ROUTINES,
    marketer_lander,
    marketer_plugin,
)

pytestmark = pytest.mark.integration


def _task(assignee: str | None) -> Task:
    return Task(
        id="content-brief",
        intent="write a blog post about why chorus exists",
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


# --- Plugin assembly ---


class TestMarketerPlugin:
    def test_plugin_name_and_outcome_kind(self) -> None:
        plugin = marketer_plugin()
        assert plugin.name == "marketer"
        assert plugin.outcome_kind == "content"

    def test_manifest_system_prompt_is_the_brief(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.system_prompt == MARKETER_BRIEF

    def test_manifest_tools_include_read_write_and_memory(self) -> None:
        plugin = marketer_plugin()
        assert "read_file" in plugin.manifest.tools
        assert "write_file" in plugin.manifest.tools
        assert "memory_search" in plugin.manifest.tools

    def test_manifest_tools_exclude_command_and_git(self) -> None:
        plugin = marketer_plugin()
        assert "run_command" not in plugin.manifest.tools
        assert "git" not in plugin.manifest.tools

    def test_manifest_permission_mode_accepts_edits(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.permission_mode == PermissionMode.ACCEPT_EDITS

    def test_manifest_isolation_is_worktree(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.isolation == Isolation.WORKTREE

    def test_manifest_sandbox_is_repo_write(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.sandbox == SandboxTier.REPO_WRITE

    def test_manifest_memory_scope_is_project(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.memory_scope == MemoryScope.PROJECT

    def test_manifest_working_memory_enabled(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.working_memory is True

    def test_no_routines_in_slice_0(self) -> None:
        plugin = marketer_plugin()
        assert plugin.declared_routines == ()
        assert MARKETER_ROUTINES == ()


# --- DoD ---


class TestMarketerDoD:
    def test_dod_is_agent_review(self) -> None:
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        assert verifier.kind == DoDKind.AGENT_REVIEW

    def test_dod_artifact_class_is_content(self) -> None:
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        assert verifier.artifact_class == "content"

    def test_dod_rubric_mentions_brand(self) -> None:
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        assert "brand" in verifier.rubric().lower()


# --- Lander ---


class TestMarketerLander:
    def test_lander_snapshots_the_content_draft(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        worktree = workspace.worktree_for("mira")
        (worktree.path / MARKETER_CONTENT_DOC).write_text(
            "# Blog: Why Chorus Exists\n\nChorus runs the org.\n", encoding="utf-8"
        )

        artifact = asyncio.run(marketer_lander(tmp_path / "acme").land(_task("mira"), None))

        assert artifact.type is ArtifactType.ARTIFACT and artifact.is_primary is True
        assert artifact.resource_ref["kind"] == "content_draft"
        assert artifact.resource_ref["doc"] == MARKETER_CONTENT_DOC
        assert artifact.resource_ref["present"] is True
        assert artifact.resource_ref["branch"] == "chorus/mira"
        assert artifact.resource_ref["commit"]  # the snapshot sha

    def test_lander_records_a_missing_doc_as_absent(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        workspace.worktree_for("mira")  # worktree with no content file

        artifact = asyncio.run(marketer_lander(tmp_path / "acme").land(_task("mira"), None))

        assert artifact.type is ArtifactType.ARTIFACT
        assert artifact.resource_ref["present"] is False

    def test_lander_requires_an_assignee(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            asyncio.run(marketer_lander(tmp_path / "acme").land(_task(None), None))

    def test_default_landers_registers_the_content_lander(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        registry = default_landers(tmp_path, ledger=ledger)
        assert registry.get("content") is not None
