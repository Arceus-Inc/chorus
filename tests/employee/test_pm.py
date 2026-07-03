"""PM — Slice 0: plugin assembly, the grounding-floor DoD, and the doc lander (pm design doc §01-§15).

The PM's signature elevation over the thin triple is its **grounding floor** (design doc §01/§09/§10):
a decision that states no decision or cites no evidence never clears "done". That floor is a
deterministic ``Verifier.command`` on the plan doc — the same move the Marketer made (a reversible
artifact lands on an objective check, not a stochastic reviewer). These tests pin the floor's shape and
prove it gates a cited plan in and an uncited one out.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.outcomes import ArtifactType, DoDKind
from chorus.roles import default_roles
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, SandboxTier
from chorus.workspace import CompanyWorkspace
from chorus_employee import default_landers
from chorus_employee.pm import (
    PM_BRIEF,
    PM_PLAN_DOC,
    PM_ROUTINES,
    pm_lander,
    pm_plugin,
)

pytestmark = pytest.mark.integration


def _task(assignee: str | None) -> Task:
    return Task(
        id="decide-brief",
        intent="decide whether to build presence indicators next",
        status=TaskStatus.IN_PROGRESS,
        assignee_employee_id=assignee,
    )


# --- Plugin assembly ---


class TestPmPlugin:
    def test_plugin_name_and_outcome_kind(self) -> None:
        plugin = pm_plugin()
        assert plugin.name == "pm"
        assert plugin.outcome_kind == "doc"

    def test_manifest_system_prompt_is_the_brief(self) -> None:
        assert pm_plugin().manifest.system_prompt == PM_BRIEF

    def test_brief_demands_a_decision_and_a_cited_source(self) -> None:
        # §01/§10: the floor's whole point — a decision, grounded in evidence. The brief must tell the
        # PM to write the structure the deterministic floor checks: a Decision section + ≥1 source.
        assert "## Decision" in PM_BRIEF
        assert "source" in PM_BRIEF.lower()
        assert PM_PLAN_DOC in PM_BRIEF

    def test_manifest_tools_are_read_write_only(self) -> None:
        manifest = pm_plugin().manifest
        assert "read_file" in manifest.tools
        assert "write_file" in manifest.tools
        assert "run_command" not in manifest.tools
        assert "git" not in manifest.tools

    def test_manifest_posture(self) -> None:
        manifest = pm_plugin().manifest
        assert manifest.permission_mode == PermissionMode.ACCEPT_EDITS
        assert manifest.isolation == Isolation.WORKTREE
        assert manifest.sandbox == SandboxTier.REPO_WRITE
        assert manifest.memory_scope == MemoryScope.PROJECT

    def test_declares_the_weekly_routine(self) -> None:
        assert pm_plugin().declared_routines == PM_ROUTINES

    def test_pm_is_registered_in_the_default_workforce(self) -> None:
        assert "pm" in {plugin.name for plugin in default_roles()}


# --- DoD: the grounding floor ---


class TestPmGroundingFloorDoD:
    def test_dod_is_a_deterministic_command(self) -> None:
        # The elevation: a reversible plan lands on an objective floor, not a stochastic AgentReview.
        verifier = pm_plugin().dod_generator("decide the thing")
        assert verifier.kind == DoDKind.COMMAND

    def test_dod_artifact_class_is_spec(self) -> None:
        assert pm_plugin().dod_generator("decide the thing").artifact_class == "spec"

    def test_floor_command_checks_plan_decision_and_source(self) -> None:
        verifier = pm_plugin().dod_generator("decide the thing")
        command = " ".join(step.command for step in verifier.verification_steps())
        assert PM_PLAN_DOC in command
        assert "decision" in command.lower()  # a decision heading is required
        assert "http" in command.lower()  # a cited source is required

    # --- the floor actually gates (deterministic proof, run in a temp worktree) ---

    def _floor_passes(self, tmp_path: Path, plan: str | None) -> bool:
        if plan is not None:
            (tmp_path / PM_PLAN_DOC).write_text(plan, encoding="utf-8")
        command = " ".join(
            step.command for step in pm_plugin().dod_generator("x").verification_steps()
        )
        return (
            subprocess.run(command, shell=True, cwd=tmp_path, capture_output=True).returncode == 0
        )

    def test_floor_passes_a_decision_with_a_cited_url(self, tmp_path: Path) -> None:
        plan = (
            "# Plan: Presence indicators\n\n"
            "## Decision\nBuild presence next — the retention pull is real.\n\n"
            "## Evidence\nWeekly retention is flat; see https://arceus.sh/metrics for the cohort.\n"
        )
        assert self._floor_passes(tmp_path, plan) is True

    def test_floor_rejects_a_decision_with_no_source(self, tmp_path: Path) -> None:
        plan = "# Plan\n\n## Decision\nBuild presence next. Trust me.\n"
        assert self._floor_passes(tmp_path, plan) is False

    def test_floor_rejects_a_cited_doc_with_no_decision(self, tmp_path: Path) -> None:
        plan = "# Notes\n\nSome context, and a link https://arceus.sh/x — but no decision stated.\n"
        assert self._floor_passes(tmp_path, plan) is False

    def test_floor_rejects_a_missing_plan(self, tmp_path: Path) -> None:
        assert self._floor_passes(tmp_path, None) is False


# --- Lander ---


class TestPmLander:
    def test_lander_snapshots_the_plan_doc(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        worktree = workspace.worktree_for("pat")
        (worktree.path / PM_PLAN_DOC).write_text(
            "# Plan\n\n## Decision\nShip it. Source: https://x\n", encoding="utf-8"
        )

        artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

        assert artifact.type is ArtifactType.DOC and artifact.is_primary is True
        assert artifact.resource_ref["kind"] == "plan_doc"
        assert artifact.resource_ref["doc"] == PM_PLAN_DOC
        assert artifact.resource_ref["present"] is True
        assert artifact.resource_ref["branch"] == "chorus/pat"
        assert artifact.resource_ref["commit"]

    def test_lander_records_a_missing_doc_as_absent(self, tmp_path: Path) -> None:
        workspace = CompanyWorkspace(tmp_path / "acme")
        workspace.worktree_for("pat")

        artifact = asyncio.run(pm_lander(tmp_path / "acme").land(_task("pat"), None))

        assert artifact.resource_ref["present"] is False

    def test_lander_requires_an_assignee(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            asyncio.run(pm_lander(tmp_path / "acme").land(_task(None), None))

    def test_default_landers_registers_the_doc_lander(
        self, ledger: SqliteLedger, tmp_path: Path
    ) -> None:
        registry = default_landers(tmp_path, ledger=ledger)
        assert registry.get("doc") is not None
