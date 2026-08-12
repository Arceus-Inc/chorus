"""The Designer employee — role triple, harness posture, and its Command-floor DoD (designer §02/§09).

Slice 2 (MVP): the Designer reads the design system (``DESIGN.md``), explores, self-lints with the
``design_lint`` tool, and writes a ``design_spec.md`` an engineer can build to. "Done" is a deterministic
floor — the spec exists, is substantive, and documents its tokens/components, states, and accessibility.
Subagents (Design-Critic, Explorer, UX-Researcher) and the gated handoff are later slices; these tests
lock the identity, the tool shelf (broad read, no run_command/git), and the DoD shape.
"""

from __future__ import annotations

import pytest

from chorus.ledger import RoutineConcurrency
from chorus.outcomes import DoDKind
from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode
from chorus_employee.designer import DESIGNER_BRIEF

pytestmark = pytest.mark.integration


class TestDesignerPlugin:
    def test_plugin_identity(self) -> None:
        from chorus_employee.designer import designer_plugin

        plugin = designer_plugin()
        assert plugin.name == "designer"
        assert plugin.outcome_kind == "design"

    def test_designer_is_in_the_default_roster(self) -> None:
        from chorus.roles import default_roles

        names = {p.name for p in default_roles()}
        assert "designer" in names


class TestDesignerManifest:
    def _manifest(self):
        from chorus_employee.designer import designer_plugin

        return designer_plugin().manifest

    def test_holds_design_lint_and_the_read_write_shelf(self) -> None:
        tools = self._manifest().tools
        for expected in (
            "design_lint",
            "design_exemplar",
            "read_file",
            "write_file",
            "skill",
            "browser_run",
        ):
            assert expected in tools

    def test_has_no_run_command_or_git(self) -> None:
        # Governed against shipping: it writes its spec to the worktree, never runs a build or a PR.
        tools = self._manifest().tools
        assert "run_command" not in tools
        assert "git" not in tools

    def test_brief_does_not_name_the_unavailable_command_tool(self) -> None:
        assert "run_command" not in DESIGNER_BRIEF

    def test_write_posture_is_worktree_isolated_accept_edits_project_memory(self) -> None:
        manifest = self._manifest()
        assert manifest.permission_mode is PermissionMode.ACCEPT_EDITS
        assert manifest.isolation is Isolation.WORKTREE
        assert manifest.memory_scope is MemoryScope.PROJECT
        assert manifest.working_memory is True

    def test_declares_the_design_craft_skills(self) -> None:
        manifest = self._manifest()
        assert set(manifest.skills) >= {
            "design-system-authoring",
            "design-md-exemplars",
            "token-scale-discipline",
            "wcag-conformance",
            "design-spec-writing",
        }

    def test_declared_skills_are_all_discoverable(self) -> None:
        # Every declared skill resolves to a real SKILL.md with valid frontmatter dream can load —
        # a manifest can't name a skill that isn't authored on disk.
        from pathlib import Path

        from dream.skills import load_skill_registry

        manifest = self._manifest()
        assert manifest.skills_root is not None
        registry, _shadows = load_skill_registry(project_dirs=[Path(manifest.skills_root)])
        discovered = {m.name for m in registry.list_meta()}
        assert set(manifest.skills) <= discovered

    def test_design_md_exemplar_library_is_vendored(self) -> None:
        # The design-md-exemplars skill promises a vendored library of real-world DESIGN.md files;
        # a handful of well-known ones must actually be present next to the package.
        from pathlib import Path

        import chorus_employee.designer as designer_pkg

        refs = Path(designer_pkg.__file__).parent / "references" / "awesome-design-md"
        assert refs.is_dir()
        for company in ("stripe", "linear.app", "vercel", "notion"):
            assert (refs / company / "DESIGN.md").is_file()
        # A meaningful library, not a token sample, and attribution is preserved.
        assert len(list(refs.glob("*/DESIGN.md"))) >= 50
        assert (refs / "LICENSE").is_file()
        assert (refs / "NOTICE.md").is_file()


class TestDesignerDoD:
    def test_dod_is_a_deterministic_command_floor(self) -> None:
        from chorus_employee.designer import designer_dod

        verifier = designer_dod("design the settings page")
        assert verifier.kind is DoDKind.COMMAND
        assert verifier.artifact_class == "design"

    def test_dod_command_checks_the_design_spec_and_its_sections(self) -> None:
        from chorus_employee.designer import DESIGN_SPEC_DOC, designer_dod

        (step,) = designer_dod("anything").verification_steps()
        cmd = step.command
        assert DESIGN_SPEC_DOC in cmd
        # the deterministic floor asserts the evidence sections that make on-system + a11y checkable
        assert "accessibility" in cmd.lower() or "a11y" in cmd.lower()
        assert "state" in cmd.lower()

    def test_deliverable_is_not_case_colliding_with_the_system_doc(self) -> None:
        # design_spec.md, never design.md — see the case-insensitive-FS footgun in design_lint.
        from chorus_employee.designer import DESIGN_SPEC_DOC, DESIGN_SYSTEM_DOC

        assert DESIGN_SPEC_DOC.lower() != DESIGN_SYSTEM_DOC.lower()


class TestDesignerLander:
    def test_lander_lands_the_design_kind(self, tmp_path) -> None:
        from chorus_employee.designer import designer_lander

        lander = designer_lander(tmp_path)
        assert lander.outcome_kind == "design"

    def test_lander_registered_in_default_landers(self, tmp_path) -> None:
        from chorus_employee import default_landers

        registry = default_landers(tmp_path)
        assert registry.get("design") is not None


class TestDesignerRoutines:
    def test_declares_the_standing_routines(self) -> None:
        # §14: standing routines that make the Designer a steward of the system, not a pure
        # responder. Both are read/report cadences — they mint work, never trip a gate on their own.
        from chorus_employee.designer import DESIGNER_ROUTINES, designer_plugin

        plugin = designer_plugin()
        assert plugin.declared_routines == DESIGNER_ROUTINES
        keys = {r.routine_key for r in DESIGNER_ROUTINES}
        assert keys == {"designer-system-drift-scan", "designer-accessibility-audit"}
        assert all(r.concurrency is RoutineConcurrency.COALESCE for r in DESIGNER_ROUTINES)

    def test_system_drift_scan_reads_the_design_system(self) -> None:
        from chorus_employee.designer import DESIGN_SYSTEM_DOC, DESIGNER_ROUTINES

        drift = next(r for r in DESIGNER_ROUTINES if r.routine_key == "designer-system-drift-scan")
        assert drift.schedule == "0 9 * * 1"  # weekly, Monday 09:00
        assert DESIGN_SYSTEM_DOC in drift.intent_template
        assert "do not" in drift.intent_template.lower()  # report/propose only

    def test_accessibility_audit_is_monthly_and_report_only(self) -> None:
        from chorus_employee.designer import DESIGNER_ROUTINES

        a11y = next(r for r in DESIGNER_ROUTINES if r.routine_key == "designer-accessibility-audit")
        assert a11y.schedule == "0 9 1 * *"  # monthly, 1st at 09:00
        assert "accessib" in a11y.intent_template.lower() or "a11y" in a11y.intent_template.lower()
        assert "do not" in a11y.intent_template.lower()  # report/propose only
