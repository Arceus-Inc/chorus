"""design_lint — the Design-Critic's deterministic pre-gen scan (designer §08/§10).

Pure helpers (``parse_design_tokens`` / ``lint_design``) are model-free and fully deterministic;
``DesignLintTool.execute`` wraps them in the harness observation + recovery contract. No keys, no
model, no net. The design substrate is the local ``DESIGN.md`` (tokens + guardrails); a missing system
degrades to an a11y-only pass rather than blinding the critic (mirrors ``brand_lint``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.testing import open_test_ledger
from chorus_tools._design_lint import (
    DesignFinding,
    DesignLintTool,
    DesignTokens,
    lint_design,
    parse_design_tokens,
)

pytestmark = pytest.mark.integration


# The machine-readable substrate the agent reads before it draws (designer §10) — a `---`-delimited
# token block (exact values, no ambiguity) + prose guardrails below.
_SYSTEM = """# Acme Design System
---
color.bg.danger:   "#b3261e"
color.bg.surface:  "#ffffff"
color.text.body:   "#0a0a0a"
space.scale:       [4, 8, 12, 16, 24, 32]
radius.card:       12
a11y.contrast.min: 4.5
---
## Principles & guardrails
- Clarity over density. NEVER hard-code a colour off the token scale.
## Components
- Button(variant: primary|secondary|danger), Dialog(role=alertdialog)
"""


class TestParseDesignTokens:
    def test_extracts_palette_spacing_and_contrast(self) -> None:
        tokens = parse_design_tokens(_SYSTEM)
        assert "#b3261e" in tokens.colors
        assert "#ffffff" in tokens.colors
        assert "#0a0a0a" in tokens.colors
        assert tokens.spacing == frozenset({4, 8, 12, 16, 24, 32})
        assert tokens.contrast_min == 4.5

    def test_palette_is_lowercased(self) -> None:
        tokens = parse_design_tokens('---\ncolor.x: "#AABBCC"\n---\n')
        assert "#aabbcc" in tokens.colors

    def test_absent_frontmatter_yields_empty_tokens(self) -> None:
        tokens = parse_design_tokens("# Just prose\nNo token block here.\n")
        assert tokens.is_empty
        assert tokens.colors == frozenset()
        assert tokens.spacing == frozenset()

    def test_only_the_first_block_is_the_contract(self) -> None:
        # Tokens live in the frontmatter block; a later hex in prose is NOT part of the contract.
        tokens = parse_design_tokens('---\ncolor.a: "#111111"\n---\nprose #999999 mention\n')
        assert "#111111" in tokens.colors
        assert "#999999" not in tokens.colors


class TestLintDesign:
    _TOKENS = DesignTokens(
        colors=frozenset({"#b3261e", "#ffffff", "#0a0a0a"}),
        spacing=frozenset({4, 8, 12, 16, 24, 32}),
        contrast_min=4.5,
    )

    def test_on_system_design_has_no_findings(self) -> None:
        doc = "# Settings\n\nSurface uses #ffffff with 16px padding, radius 12.\n"
        assert lint_design(doc, self._TOKENS) == ()

    def test_off_token_colour_is_flagged_with_line(self) -> None:
        doc = "# Card\n\nHeader background is #123456.\n"
        findings = lint_design(doc, self._TOKENS)
        assert len(findings) == 1
        (f,) = findings
        assert f.kind == "off_token_color"
        assert f.line == 3
        assert "#123456" in f.quote
        assert f.fix

    def test_on_token_colour_is_not_flagged(self) -> None:
        doc = "The danger surface uses #b3261e.\n"
        assert all(f.kind != "off_token_color" for f in lint_design(doc, self._TOKENS))

    def test_off_token_colour_match_is_case_insensitive(self) -> None:
        # #B3261E is on-scale once folded; an off-scale hex in any case still fires.
        assert all(f.kind != "off_token_color" for f in lint_design("uses #B3261E\n", self._TOKENS))
        (f,) = [
            f for f in lint_design("uses #ABCDEF\n", self._TOKENS) if f.kind == "off_token_color"
        ]
        assert f.kind == "off_token_color"

    def test_off_scale_spacing_is_flagged(self) -> None:
        doc = "Set padding to 20px around the field.\n"
        assert any(f.kind == "off_scale_spacing" for f in lint_design(doc, self._TOKENS))

    def test_on_scale_spacing_is_not_flagged(self) -> None:
        doc = "Gap is 8px; outer margin 24px.\n"
        assert all(f.kind != "off_scale_spacing" for f in lint_design(doc, self._TOKENS))

    def test_interactive_element_without_a11y_note_is_flagged(self) -> None:
        doc = "A Dialog opens when the row is clicked.\n"
        assert any(f.kind == "missing_a11y_note" for f in lint_design(doc, self._TOKENS))

    def test_interactive_element_with_a11y_note_is_not_flagged(self) -> None:
        doc = "A Dialog (role=alertdialog) traps focus and is closable by keyboard.\n"
        assert all(f.kind != "missing_a11y_note" for f in lint_design(doc, self._TOKENS))

    def test_empty_tokens_skip_colour_and_spacing_checks(self) -> None:
        # No system contract → cannot judge off-token; only the a11y heuristic runs (degrade, not blind).
        doc = "Header #123456, padding 20px.\n"
        findings = lint_design(doc, DesignTokens.empty())
        assert all(f.kind not in ("off_token_color", "off_scale_spacing") for f in findings)

    def test_findings_are_sorted_by_line_then_kind(self) -> None:
        doc = "A Dialog on #123456 with 20px inset.\nA calm second line.\n"
        findings = lint_design(doc, self._TOKENS)
        keys = [(f.line, f.kind) for f in findings]
        assert keys == sorted(keys)

    def test_finding_is_an_immutable_dataclass(self) -> None:
        (f,) = [
            f for f in lint_design("uses #ABCDEF\n", self._TOKENS) if f.kind == "off_token_color"
        ]
        assert isinstance(f, DesignFinding)
        with pytest.raises((AttributeError, Exception)):
            f.kind = "x"  # type: ignore[misc]  # frozen


# --- Tool: harness observation + recovery contract ---


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: DesignLintTool, ctx: object, payload: dict[str, object]) -> object:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


class TestDesignLintTool:
    def _seed(self, tmp_path: Path, *, doc: str, system: str | None = _SYSTEM) -> None:
        # NB: the deliverable is `design_spec.md`, NOT `design.md` — on a case-insensitive filesystem
        # (Windows/macOS) `design.md` and the `DESIGN.md` system file are the SAME path and collide.
        (tmp_path / "design_spec.md").write_text(doc, encoding="utf-8")
        if system is not None:
            (tmp_path / "DESIGN.md").write_text(system, encoding="utf-8")

    def test_on_system_design_reports_success_no_findings(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="# Settings\n\nSurface #ffffff, padding 16px, radius 12.\n")
        result = _run(DesignLintTool(), _ctx(tmp_path), {"doc": "design_spec.md"})
        assert result.is_error is False
        assert result.metadata["status"] == "success"
        assert result.metadata["findings"] == []

    def test_broken_design_warns_with_all_kinds(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="# X\n\nA Dialog on #123456 with 20px inset.\n")
        result = _run(DesignLintTool(), _ctx(tmp_path), {"doc": "design_spec.md"})
        assert result.is_error is False
        assert result.metadata["status"] == "warning"
        kinds = {f["kind"] for f in result.metadata["findings"]}
        assert "off_token_color" in kinds
        assert "off_scale_spacing" in kinds
        assert "missing_a11y_note" in kinds
        assert result.metadata["next_actions"]
        assert result.metadata["artifacts"]["doc"] == "design_spec.md"

    def test_missing_doc_is_a_fail_closed_error(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="x", system=_SYSTEM)
        result = _run(DesignLintTool(), _ctx(tmp_path), {"doc": "does_not_exist.md"})
        assert result.is_error is True
        assert result.metadata["root_cause"]
        assert result.metadata["safe_retry"]
        assert result.metadata["stop_condition"]

    def test_missing_system_degrades_to_a11y_only(self, tmp_path: Path) -> None:
        # No DESIGN.md → off-token/off-scale cannot be judged; the a11y pass still runs.
        self._seed(tmp_path, doc="A Dialog on #123456 with 20px inset.\n", system=None)
        result = _run(DesignLintTool(), _ctx(tmp_path), {"doc": "design_spec.md"})
        assert result.is_error is False
        kinds = {f["kind"] for f in result.metadata["findings"]}
        assert "missing_a11y_note" in kinds
        assert "off_token_color" not in kinds
        assert "off_scale_spacing" not in kinds

    def test_bad_input_is_rejected(self, tmp_path: Path) -> None:
        result = _run(DesignLintTool(), _ctx(tmp_path), {"doc": ""})
        assert result.is_error is True
        assert result.metadata["root_cause"]


class TestWiring:
    def test_capability_tool_registers_design_lint(self) -> None:
        from chorus.roles import RoleRegistry
        from chorus_harness._factory import _capability_tool

        ledger = open_test_ledger()
        try:
            tool = _capability_tool("design_lint", ledger, RoleRegistry())
            assert isinstance(tool, DesignLintTool)
        finally:
            ledger.close()
