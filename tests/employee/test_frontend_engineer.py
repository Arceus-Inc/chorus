"""The Frontend Engineer employee — role triple, harness posture, and its evidence-bundle DoD.

The Frontend Engineer builds a working frontend app in its worktree — in whatever stack it judges best
(vanilla, React, Vue, Svelte, …) — writes and RUNS unit + e2e tests, and lands a durable
``test_evidence/`` bundle. "Done" is a deterministic, cross-platform, FRAMEWORK-AGNOSTIC floor: a real
runnable project (a ``package.json`` with a wired ``test`` script), a Playwright end-to-end harness, and
the captured evidence — all substantive. These tests lock the identity, the build-tool shelf, the trust
posture, and — via a real shell round-trip — that the cross-platform DoD floor actually gates on this OS.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chorus.outcomes import DoDKind
from chorus.roles._manifest import (
    DREAM_DEFAULT_MAX_SPRINTS,
    Isolation,
    MemoryScope,
    PermissionMode,
    SandboxTier,
)

pytestmark = pytest.mark.integration


def _run_floor(command: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run the DoD command through the OS shell exactly as dream's verification oracle does."""
    return subprocess.run(command, shell=True, cwd=cwd, capture_output=True, text=True, check=False)


def _complete_worktree(root: Path) -> None:
    """Materialise a worktree that satisfies the full framework-agnostic evidence contract."""
    (root / "package.json").write_text(
        "{\n"
        '  "name": "app",\n'
        '  "private": true,\n'
        '  "scripts": {\n'
        '    "test": "node --test",\n'
        '    "build": "true"\n'
        "  }\n"
        "}\n",
        encoding="utf-8",
    )
    (root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\nexport default defineConfig({});\n",
        encoding="utf-8",
    )
    ev = root / "test_evidence"
    ev.mkdir()
    (ev / "unit.txt").write_text("# tests 1\n# pass 1\n# fail 0\nok 1 - add\n", encoding="utf-8")
    (ev / "e2e.txt").write_text(
        "Running 1 test using 1 worker\n  1 passed (1.2s)\n", encoding="utf-8"
    )
    (ev / "summary.md").write_text(
        "# Test evidence\n\n"
        "## Stack decision\n"
        "I chose a small dependency-light stack for this slice because the surface is a single view with "
        "simple local state; a heavier framework would not have earned its cost here. The rationale and "
        "trade-off are recorded so a reviewer can judge the choice.\n\n"
        "This build ships a counter wired with an event listener that updates the DOM. The unit tests "
        "cover the pure reducer and its edge cases; the Playwright e2e test drives the real button click "
        "and asserts the visible result updates. Both suites pass. Accessibility: the control is a "
        "semantic button with an accessible name, keyboard operable, with a visible focus ring and AA "
        "contrast. Loading, empty, and error states are handled. " + "word " * 60,
        encoding="utf-8",
    )


class TestFrontendEngineerPlugin:
    def test_plugin_identity(self) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_plugin

        plugin = frontend_engineer_plugin()
        assert plugin.name == "frontend_engineer"
        # lands running code — shares the Engineer's `pr` outcome + lander.
        assert plugin.outcome_kind == "pr"

    def test_is_in_the_default_roster(self) -> None:
        from chorus.roles import default_roles

        names = {p.name for p in default_roles()}
        assert "frontend_engineer" in names

    def test_registers_cleanly_in_the_validated_role_registry(self) -> None:
        # The whole default workforce (now including this role) assembles without RolePluginInvalid /
        # RolePluginConflict — name unique, enums legal, routines minimal.
        from chorus.roles import RoleRegistry, default_roles

        registry = RoleRegistry.from_plugins(default_roles())
        assert registry.get("frontend_engineer").outcome_kind == "pr"


class TestFrontendEngineerManifest:
    def _manifest(self):
        from chorus_employee.frontend_engineer import frontend_engineer_plugin

        return frontend_engineer_plugin().manifest

    def test_holds_the_build_tool_shelf(self) -> None:
        tools = self._manifest().tools
        for expected in ("read_file", "write_file", "run_command", "git"):
            assert expected in tools, expected

    def test_holds_web_research_for_grounding(self) -> None:
        tools = self._manifest().tools
        assert "browser_run" in tools
        assert "browser_run" in tools

    def test_holds_the_memory_shelf(self) -> None:
        tools = self._manifest().tools
        for expected in ("memory_search", "memory_get", "working_memory_write", "memory_propose"):
            assert expected in tools, expected

    def test_trust_posture_is_unrestricted_to_run_tests(self) -> None:
        # It must run node/npm/npx-playwright/a static server; a lower tier gates commands behind an
        # interactive approval the kernel can't supply.
        assert self._manifest().sandbox is SandboxTier.UNRESTRICTED

    def test_write_posture_is_worktree_isolated_accept_edits_project_memory(self) -> None:
        manifest = self._manifest()
        assert manifest.permission_mode is PermissionMode.ACCEPT_EDITS
        assert manifest.isolation is Isolation.WORKTREE
        assert manifest.memory_scope is MemoryScope.PROJECT
        assert manifest.working_memory is True

    def test_budgets_are_widened_for_a_build_test_iterate_loop(self) -> None:
        manifest = self._manifest()
        assert manifest.max_turns >= 12
        assert manifest.max_sprints == DREAM_DEFAULT_MAX_SPRINTS
        assert manifest.max_sprints >= 2
        assert manifest.beat_timeout_s is not None and manifest.beat_timeout_s >= 900
        assert manifest.lease_ttl_s is not None and manifest.lease_ttl_s >= manifest.beat_timeout_s


class TestFrontendEngineerSkills:
    def _manifest(self):
        from chorus_employee.frontend_engineer import frontend_engineer_plugin

        return frontend_engineer_plugin().manifest

    def test_holds_the_skill_tool(self) -> None:
        # The `skill` tool is how the authored craft playbooks get loaded on demand.
        assert "skill" in self._manifest().tools

    def test_declares_the_build_and_testing_craft_skills(self) -> None:
        # A representative core of the library must be declared: scoping, the framework-agnostic stack
        # decision, a11y, both test layers, and the evidence discipline that makes the work verifiable.
        assert set(self._manifest().skills) >= {
            "spec-to-working-app",
            "choosing-a-frontend-stack",
            "semantic-html-and-aria",
            "keyboard-and-focus",
            "unit-testing-with-node-test",
            "playwright-e2e-authoring",
            "test-evidence-discipline",
        }

    def test_declared_skills_are_all_discoverable(self) -> None:
        # Every declared skill resolves to a real SKILL.md with valid frontmatter dream can load —
        # a manifest can't name a skill that isn't authored on disk.
        from dream.skills import load_skill_registry

        manifest = self._manifest()
        assert manifest.skills_root is not None
        registry, _shadows = load_skill_registry(project_dirs=[Path(manifest.skills_root)])
        discovered = {m.name for m in registry.list_meta()}
        assert set(manifest.skills) <= discovered

    def test_skills_root_points_at_this_packages_skills_dir(self) -> None:
        manifest = self._manifest()
        assert manifest.skills_root is not None
        root = Path(manifest.skills_root)
        assert root.is_dir()
        assert root.name == "skills"
        # each declared skill is a directory holding a SKILL.md
        for name in manifest.skills:
            assert (root / name / "SKILL.md").is_file(), name


class TestFrontendEngineerDoD:
    def test_dod_is_a_deterministic_command_floor_landing_a_pr(self) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        verifier = frontend_engineer_dod("build a counter")
        assert verifier.kind is DoDKind.COMMAND
        assert verifier.artifact_class == "pr"

    def test_dod_is_a_cross_platform_python_command(self) -> None:
        # The floor is authored as a python -c invocation (runs under cmd.exe AND /bin/sh); the checked
        # paths live in the base64 envelope, never in cleartext where a shell could reinterpret them.
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        (step,) = frontend_engineer_dod("anything").verification_steps()
        assert " -c " in step.command
        assert "import base64" in step.command
        assert "test_evidence" not in step.command  # encoded, not cleartext

    def test_floor_passes_on_a_complete_worktree(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        (step,) = frontend_engineer_dod("anything").verification_steps()
        result = _run_floor(step.command, tmp_path)
        assert result.returncode == 0, result.stderr

    def test_floor_fails_when_the_evidence_bundle_is_missing(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        # remove the whole evidence bundle
        for name in ("unit.txt", "e2e.txt", "summary.md"):
            (tmp_path / "test_evidence" / name).unlink()
        (step,) = frontend_engineer_dod("anything").verification_steps()
        result = _run_floor(step.command, tmp_path)
        assert result.returncode != 0
        assert "DoD FAIL" in result.stderr

    def test_floor_fails_without_the_e2e_harness(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        (tmp_path / "playwright.config.ts").unlink()
        (step,) = frontend_engineer_dod("anything").verification_steps()
        assert _run_floor(step.command, tmp_path).returncode != 0

    def test_floor_fails_without_a_test_script(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        # a package.json with no `test` script — the unit runner is not wired.
        (tmp_path / "package.json").write_text(
            '{\n  "name": "app",\n  "scripts": {\n    "build": "true"\n  }\n}\n', encoding="utf-8"
        )
        (step,) = frontend_engineer_dod("anything").verification_steps()
        assert _run_floor(step.command, tmp_path).returncode != 0

    def test_floor_fails_on_a_thin_summary(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        (tmp_path / "test_evidence" / "summary.md").write_text("too short\n", encoding="utf-8")
        (step,) = frontend_engineer_dod("anything").verification_steps()
        assert _run_floor(step.command, tmp_path).returncode != 0

    def test_floor_fails_without_a_project(self, tmp_path: Path) -> None:
        from chorus_employee.frontend_engineer import frontend_engineer_dod

        _complete_worktree(tmp_path)
        (tmp_path / "package.json").unlink()
        (step,) = frontend_engineer_dod("anything").verification_steps()
        assert _run_floor(step.command, tmp_path).returncode != 0


class TestFrontendEngineerOutcome:
    def test_reuses_the_engineers_pr_lander(self, tmp_path: Path) -> None:
        # It declares outcome_kind "pr" and lands running code, so it shares the Engineer's registered
        # `pr` lander rather than declaring its own.
        from chorus_employee import default_landers

        registry = default_landers(tmp_path)
        assert registry.get("pr") is not None


class TestFrontendEngineerRoutines:
    def test_declares_no_standing_routines(self) -> None:
        from chorus_employee.frontend_engineer import FRONTEND_ENGINEER_ROUTINES

        assert FRONTEND_ENGINEER_ROUTINES == ()
