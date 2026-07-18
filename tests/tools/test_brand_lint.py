"""brand_lint — the Brand-Critic's deterministic pre-gen scan (design doc §08/§10).

Pure helpers (``parse_prohibited_phrases`` / ``lint_text``) are model-free and fully deterministic;
``BrandLintTool.execute`` wraps them in the harness observation + recovery contract. No keys, no model.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.testing import open_test_ledger
from chorus_tools._brand_lint import (
    BrandFinding,
    BrandLintTool,
    lint_text,
    parse_prohibited_phrases,
)

pytestmark = pytest.mark.integration


_SPEC = """# Arceus Brand Voice Specification
## Tone
- Technical, direct, confident.
## Prohibited Phrases
- revolutionary, game-changing, 10x, unlock
## Claim Policy
- Substantiate or hedge every performance claim.
"""


class TestParseProhibitedPhrases:
    def test_extracts_csv_list_under_the_heading(self) -> None:
        assert parse_prohibited_phrases(_SPEC) == (
            "revolutionary",
            "game-changing",
            "10x",
            "unlock",
        )

    def test_absent_section_falls_back_to_defaults(self) -> None:
        phrases = parse_prohibited_phrases("# Spec\n## Tone\n- be nice\n")
        assert phrases  # non-empty fallback
        assert "game-changing" in phrases  # a sensible default

    def test_heading_match_is_case_insensitive(self) -> None:
        assert parse_prohibited_phrases("## PROHIBITED PHRASES\n- foo, bar\n") == ("foo", "bar")


class TestLintText:
    _PHRASES = ("revolutionary", "game-changing", "10x")

    def test_clean_draft_has_no_findings(self) -> None:
        doc = "# Post\n\nWe built a tool that indexes a 2M-line repo. We believe it helps.\n"
        assert lint_text(doc, self._PHRASES) == ()

    def test_prohibited_phrase_is_flagged_with_line(self) -> None:
        doc = "# Post\n\nThis is a game-changing release.\n"
        findings = lint_text(doc, self._PHRASES)
        assert len(findings) == 1
        (f,) = findings
        assert f.kind == "prohibited_phrase"
        assert f.line == 3
        assert "game-changing" in f.quote.lower()
        assert f.fix  # non-empty remedy

    def test_prohibited_phrase_match_is_case_insensitive(self) -> None:
        doc = "Our Revolutionary approach.\n"
        (f,) = lint_text(doc, self._PHRASES)
        assert f.kind == "prohibited_phrase"

    def test_bare_metric_stated_as_fact_is_flagged(self) -> None:
        doc = "It cuts build time 40% for every team.\n"
        findings = lint_text(doc, self._PHRASES)
        assert any(f.kind == "unsubstantiated_claim" for f in findings)

    def test_hedged_metric_is_not_flagged(self) -> None:
        doc = "We believe it cuts build time by around 40%.\n"
        assert all(f.kind != "unsubstantiated_claim" for f in lint_text(doc, self._PHRASES))

    def test_cited_metric_is_not_flagged(self) -> None:
        doc = "It cut build time 40% (internal benchmark, Q2) [1].\n"
        assert all(f.kind != "unsubstantiated_claim" for f in lint_text(doc, self._PHRASES))

    def test_guarantee_without_hedge_is_flagged(self) -> None:
        doc = "This will eliminate all your flaky tests.\n"
        assert any(f.kind == "unsubstantiated_claim" for f in lint_text(doc, self._PHRASES))

    def test_findings_are_sorted_by_line_then_kind(self) -> None:
        doc = "A game-changing tool that will save you 10 hours.\nA calm second line.\n"
        findings = lint_text(doc, self._PHRASES)
        keys = [(f.line, f.kind) for f in findings]
        assert keys == sorted(keys)

    def test_finding_is_an_immutable_dataclass(self) -> None:
        (f,) = lint_text("A game-changing tool.\n", self._PHRASES)
        assert isinstance(f, BrandFinding)
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


def _run(tool: BrandLintTool, ctx: object, payload: dict[str, object]) -> object:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


class TestBrandLintTool:
    def _seed(self, tmp_path: Path, *, doc: str, spec: str | None = _SPEC) -> None:
        (tmp_path / "content_draft.md").write_text(doc, encoding="utf-8")
        if spec is not None:
            (tmp_path / "brand_spec.md").write_text(spec, encoding="utf-8")

    def test_clean_draft_reports_success_no_findings(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="# Post\n\nWe believe this helps teams ship.\n")
        result = _run(BrandLintTool(), _ctx(tmp_path), {"doc": "content_draft.md"})
        assert result.is_error is False
        assert result.metadata["status"] == "success"
        assert result.metadata["findings"] == []

    def test_violating_draft_warns_with_both_kinds(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="# Post\n\nA game-changing tool that cuts build time 40%.\n")
        result = _run(BrandLintTool(), _ctx(tmp_path), {"doc": "content_draft.md"})
        assert result.is_error is False
        assert result.metadata["status"] == "warning"
        kinds = {f["kind"] for f in result.metadata["findings"]}
        assert "prohibited_phrase" in kinds
        assert "unsubstantiated_claim" in kinds
        assert result.metadata["next_actions"]
        assert result.metadata["artifacts"]["doc"] == "content_draft.md"

    def test_missing_doc_is_a_fail_closed_error(self, tmp_path: Path) -> None:
        self._seed(tmp_path, doc="x", spec=_SPEC)
        result = _run(BrandLintTool(), _ctx(tmp_path), {"doc": "does_not_exist.md"})
        assert result.is_error is True
        assert result.metadata["root_cause"]
        assert result.metadata["safe_retry"]
        assert result.metadata["stop_condition"]

    def test_missing_spec_degrades_to_defaults(self, tmp_path: Path) -> None:
        # A missing brand spec should degrade (fallback list), not blind the critic.
        self._seed(tmp_path, doc="A game-changing tool.\n", spec=None)
        result = _run(BrandLintTool(), _ctx(tmp_path), {"doc": "content_draft.md"})
        assert result.is_error is False
        assert result.metadata["status"] == "warning"
        assert any(f["kind"] == "prohibited_phrase" for f in result.metadata["findings"])

    def test_bad_input_is_rejected(self, tmp_path: Path) -> None:
        result = _run(BrandLintTool(), _ctx(tmp_path), {"doc": ""})
        assert result.is_error is True
        assert result.metadata["root_cause"]


class TestWiring:
    def test_capability_tool_registers_brand_lint(self) -> None:
        from chorus.roles import RoleRegistry
        from chorus_harness._factory import _capability_tool

        ledger = open_test_ledger()
        try:
            tool = _capability_tool("brand_lint", ledger, RoleRegistry())
            assert isinstance(tool, BrandLintTool)
        finally:
            ledger.close()

    def test_marketer_holds_brand_lint(self) -> None:
        from chorus_employee.marketer import marketer_plugin

        assert "brand_lint" in marketer_plugin().manifest.tools
