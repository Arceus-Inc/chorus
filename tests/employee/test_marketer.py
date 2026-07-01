"""Marketer — Slice 0: plugin assembly, manifest shape, DoD, and lander (design doc §01-§15)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.ledger import RoutineConcurrency, SqliteLedger, Task, TaskStatus
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

    def test_manifest_includes_web_search_for_research(self) -> None:
        # §06 Researcher / §07 read reach: Tavily-backed web search for market/audience research.
        assert "web_search" in marketer_plugin().manifest.tools

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

    def test_manifest_sandbox_is_repo_write_net(self) -> None:
        # REPO_WRITE_NET: drafts to her worktree + allowlisted egress (web_search → api.tavily.com).
        # No arbitrary network, no commands; the gated stage_go_live is her only outbound-write surface.
        plugin = marketer_plugin()
        assert plugin.manifest.sandbox == SandboxTier.REPO_WRITE_NET

    def test_manifest_memory_scope_is_project(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.memory_scope == MemoryScope.PROJECT

    def test_manifest_working_memory_enabled(self) -> None:
        plugin = marketer_plugin()
        assert plugin.manifest.working_memory is True

    def test_manifest_widens_beat_budget_for_research(self) -> None:
        # She spawns a multi-minute web_research sweep; the org defaults (90s beat / 300s lease) would
        # reap her mid-research, so the role carries a wider beat_timeout_s + lease_ttl_s.
        manifest = marketer_plugin().manifest
        assert manifest.beat_timeout_s is not None and manifest.beat_timeout_s >= 300.0
        assert manifest.lease_ttl_s is not None and manifest.lease_ttl_s >= manifest.beat_timeout_s
        # And the projection carries both through to the beat config.
        from chorus.roles import role_beat_config

        config = role_beat_config(manifest)
        assert config.beat_timeout_s == manifest.beat_timeout_s
        assert config.lease_ttl_s == manifest.lease_ttl_s

    def test_declares_the_brand_drift_scan(self) -> None:
        # §13: the first standing routine — a weekly read/report cadence against the voice spec.
        plugin = marketer_plugin()
        assert plugin.declared_routines == MARKETER_ROUTINES
        assert len(MARKETER_ROUTINES) == 1
        (routine,) = MARKETER_ROUTINES
        assert routine.routine_key == "marketer-brand-drift-scan"
        assert routine.schedule == "0 9 * * 1"  # weekly, Monday 09:00
        assert routine.concurrency is RoutineConcurrency.COALESCE
        assert "brand_spec.md" in routine.intent_template


# --- DoD ---


class TestMarketerDoD:
    def test_dod_is_command(self) -> None:
        # Slice 1: a reversible draft lands on a deterministic Command, not a stochastic
        # AgentReview — brand fidelity is enforced in-beat by the Brand-Critic (§06/§10).
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        assert verifier.kind == DoDKind.COMMAND

    def test_dod_artifact_class_is_content(self) -> None:
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        assert verifier.artifact_class == "content"

    def test_dod_command_checks_the_content_draft(self) -> None:
        plugin = marketer_plugin()
        verifier = plugin.dod_generator("write a blog post")
        commands = " ".join(step.command for step in verifier.verification_steps())
        assert "content_draft.md" in commands
        assert "wc -w" in commands  # substantive-length floor, not just existence


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
