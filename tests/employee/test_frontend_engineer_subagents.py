"""Frontend Engineer — subagents slice: the Code-Reviewer and UI-Tester declarations + wiring.

Structural twin of ``test_designer_subagents.py``. The Designer's post-draft Design-Critic maps here to
a post-BUILD review layer: a Code-Reviewer (correctness / accessibility / test integrity) and a UI-Tester
(auditor of the PROOF — does the e2e genuinely drive + assert the real UI). Both are read-only and both
ground their verdict on the deterministic ``evidence_scan`` scan (the structural analog of the Designer's
``design_lint``).

The *declaration*-level tests run everywhere; the *projection*-level tests (``_subagent_set``) exercise
dream's ``Subagent`` projection, which requires a ``spawnable``-aware dream — guarded by
:data:`_DREAM_HAS_SPAWNABLE` so the suite stays green against an older dream and lights up automatically
once dream is updated.
"""

from __future__ import annotations

import pytest

from chorus.roles import role_beat_config
from chorus.testing import open_test_ledger
from chorus_employee.frontend_engineer import frontend_engineer_plugin
from chorus_employee.frontend_engineer._subagents import (
    CODE_REVIEWER_SUBAGENT,
    UI_TESTER_SUBAGENT,
)
from chorus_harness._factory import _subagent_set

pytestmark = pytest.mark.integration

# dream's Subagent must accept `spawnable=` before the factory can project specs (``_project_spec``
# always passes it, even the empty tuple for a leaf). When the installed dream predates that field,
# chorus's `_project_spec` raises TypeError — skip projection tests (not role bugs) rather than fail
# them. Declaration-level coverage is unaffected.
try:  # pragma: no cover - trivial capability probe
    from dream.subagents._declaration import Subagent as _DreamSubagent

    _DREAM_HAS_SPAWNABLE = "spawnable" in getattr(_DreamSubagent, "__dataclass_fields__", {})
except Exception:  # pragma: no cover - dream import shape changed
    _DREAM_HAS_SPAWNABLE = False

_needs_spawnable = pytest.mark.skipif(
    not _DREAM_HAS_SPAWNABLE,
    reason="installed dream.Subagent lacks `spawnable`; factory projection blocked (pre-existing env mismatch)",
)


# --- Code-Reviewer declaration (Design-Critic twin) ---


class TestCodeReviewerDeclaration:
    def test_subagent_name(self) -> None:
        assert CODE_REVIEWER_SUBAGENT.name == "code_reviewer"

    def test_subagent_is_read_only(self) -> None:
        # It judges the code; it never edits or runs. The engineer keeps ownership of every fix.
        assert "write_file" not in CODE_REVIEWER_SUBAGENT.tools
        assert "run_command" not in CODE_REVIEWER_SUBAGENT.tools
        assert "read_file" in CODE_REVIEWER_SUBAGENT.tools

    def test_subagent_max_turns_bounded(self) -> None:
        assert CODE_REVIEWER_SUBAGENT.max_turns <= 8

    def test_description_mentions_correctness_accessibility_and_tests(self) -> None:
        # The child's system prompt is generated from the description, so the full brief lives there.
        desc = CODE_REVIEWER_SUBAGENT.description.lower()
        assert "correct" in desc
        assert "accessib" in desc or "a11y" in desc
        assert "test" in desc

    def test_description_instructs_pass_fail_verdict(self) -> None:
        desc = CODE_REVIEWER_SUBAGENT.description
        assert "PASS" in desc
        assert "FAIL" in desc

    def test_description_instructs_read_only(self) -> None:
        desc = CODE_REVIEWER_SUBAGENT.description.lower()
        assert "read-only" in desc or "read only" in desc

    def test_grounds_verdict_on_test_evidence(self) -> None:
        # test_evidence is the deterministic primitive it runs first, then reasons past it.
        assert "evidence_scan" in CODE_REVIEWER_SUBAGENT.tools
        assert "evidence_scan" in CODE_REVIEWER_SUBAGENT.description

    def test_carries_the_verdict_output_schema(self) -> None:
        schema = CODE_REVIEWER_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"verdict", "issues"} <= set(schema["required"])
        assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]


# --- UI-Tester declaration (the proof auditor) ---


class TestUiTesterDeclaration:
    def test_subagent_name(self) -> None:
        assert UI_TESTER_SUBAGENT.name == "ui_tester"

    def test_subagent_is_read_only(self) -> None:
        assert "write_file" not in UI_TESTER_SUBAGENT.tools
        assert "run_command" not in UI_TESTER_SUBAGENT.tools
        assert "read_file" in UI_TESTER_SUBAGENT.tools

    def test_subagent_max_turns_bounded(self) -> None:
        assert UI_TESTER_SUBAGENT.max_turns <= 8

    def test_description_is_about_e2e_proof(self) -> None:
        desc = UI_TESTER_SUBAGENT.description.lower()
        assert "e2e" in desc
        assert "proof" in desc or "prove" in desc

    def test_description_instructs_pass_fail_verdict(self) -> None:
        desc = UI_TESTER_SUBAGENT.description
        assert "PASS" in desc
        assert "FAIL" in desc

    def test_description_instructs_read_only(self) -> None:
        desc = UI_TESTER_SUBAGENT.description.lower()
        assert "read-only" in desc or "read only" in desc

    def test_grounds_verdict_on_test_evidence(self) -> None:
        assert "evidence_scan" in UI_TESTER_SUBAGENT.tools
        assert "evidence_scan" in UI_TESTER_SUBAGENT.description

    def test_carries_the_verdict_output_schema(self) -> None:
        schema = UI_TESTER_SUBAGENT.output_schema
        assert schema is not None
        assert schema.get("type") == "object"
        assert {"verdict", "gaps"} <= set(schema["required"])
        assert schema["properties"]["verdict"]["enum"] == ["PASS", "FAIL"]


# --- Manifest integration ---


class TestFrontendEngineerManifestSubagents:
    def _manifest(self):
        return frontend_engineer_plugin().manifest

    def test_manifest_declares_code_reviewer(self) -> None:
        assert any(sa.name == "code_reviewer" for sa in self._manifest().subagents)

    def test_manifest_declares_ui_tester(self) -> None:
        assert any(sa.name == "ui_tester" for sa in self._manifest().subagents)

    def test_manifest_includes_spawn_subagent_tool(self) -> None:
        assert "spawn_subagent" in self._manifest().tools

    def test_reviewers_get_test_evidence_as_a_subagent_primitive(self) -> None:
        manifest = self._manifest()
        # parent superset (needed so the projection's narrower-wins intersection keeps it)
        assert "evidence_scan" in manifest.tools
        for name in ("code_reviewer", "ui_tester"):
            sa = next(s for s in manifest.subagents if s.name == name)
            assert "evidence_scan" in sa.tools

    def test_subagent_tools_are_subset_of_parent_tools(self) -> None:
        manifest = self._manifest()
        parent_tools = set(manifest.tools)
        for subagent in manifest.subagents:
            for tool in subagent.tools:
                assert tool in parent_tools, (
                    f"Subagent tool {tool!r} is not in parent's tools — narrower-wins violation"
                )

    def test_beat_config_carries_the_subagents(self) -> None:
        config = role_beat_config(self._manifest())
        assert {sa.name for sa in config.subagents} == {"code_reviewer", "ui_tester"}


# --- Factory projection (guarded on dream `spawnable` support) ---


@_needs_spawnable
class TestFrontendEngineerProjection:
    def _config(self):
        return role_beat_config(frontend_engineer_plugin().manifest)

    def test_code_reviewer_projects_read_only_with_test_evidence(self) -> None:
        result = _subagent_set(self._config())
        assert result is not None
        child = result.get("code_reviewer")
        assert child is not None
        assert child.max_turns <= 8
        assert "read_file" in child.tools
        assert "evidence_scan" in child.tools
        assert "write_file" not in child.tools  # read-only survives projection
        assert "run_command" not in child.tools

    def test_ui_tester_projects_read_only_with_test_evidence(self) -> None:
        result = _subagent_set(self._config())
        assert result is not None
        child = result.get("ui_tester")
        assert child is not None
        assert "read_file" in child.tools
        assert "evidence_scan" in child.tools
        assert "write_file" not in child.tools
        assert child.output_schema is not None

    def test_test_evidence_is_actually_offered_to_the_reviewer_at_runtime(self) -> None:
        from dream.permissions._types import SandboxTier
        from dream.roles._toolset import compute_minimum_toolset
        from dream.subagents._inline_executor import _build_subagent_manifest
        from dream.tools._registry import ToolSource

        import chorus_harness._factory as factory
        from chorus.roles import RoleRegistry

        config = self._config()
        ledger = open_test_ledger()
        try:
            registry = factory._role_registry(factory.dream_tool_names(config.tools))
            for name in config.tools:
                cap = factory._capability_tool(name, ledger, RoleRegistry())
                if cap is not None:
                    registry.register(cap, source=ToolSource.DEFAULT)
            declarations = {t.name: t.declaration for t in registry.list_tools()}
            assert "evidence_scan" in declarations

            reviewer = _subagent_set(config).get("code_reviewer")  # type: ignore[union-attr]
            assert reviewer is not None
            parent_ceiling = frozenset(declarations)
            manifest = _build_subagent_manifest(reviewer, parent_tools=parent_ceiling)
            offered = compute_minimum_toolset(
                manifest, sandbox_tier=SandboxTier.UNRESTRICTED, declarations=declarations
            )
            assert "evidence_scan" in offered
        finally:
            ledger.close()
