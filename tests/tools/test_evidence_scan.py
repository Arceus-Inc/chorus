"""test_evidence — the Frontend Engineer's deterministic pre-done scan of its own test bundle.

Pure helpers (:func:`assess_log` / :func:`scan_evidence`) are model-free and fully deterministic;
:class:`EvidenceScanTool.execute` wraps them in the harness observation + recovery contract. No keys,
no model, no net. The substrate is the worktree's ``test_evidence/`` bundle + the suites that produced
it; going beyond the DoD floor, it also reads each captured log for *failures* and the summary for
substance (the exact structural analog of ``design_lint``'s mechanical + advisory split).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus_tools._evidence_scan import (
    EvidenceScanTool,
    assess_log,
    scan_evidence,
)

pytestmark = pytest.mark.integration


# --- captured-log fixtures (what the real runners actually print) ------------------------------------
_NODE_GREEN = "TAP version 13\nok 1 - add\n1..1\n# tests 1\n# pass 1\n# fail 0\n"
_NODE_RED = "TAP version 13\nnot ok 1 - add\n1..1\n# tests 1\n# pass 0\n# fail 1\n"
_PW_GREEN = "Running 1 test using 1 worker\n  ✓  1 e2e/flow.spec.js (1.2s)\n\n  1 passed (1.4s)\n"
_PW_RED = "Running 2 tests using 1 worker\n  ✘  1 e2e/flow.spec.js\n\n  1 failed\n  1 passed\n"


class TestAssessLog:
    def test_absent_log_reads_as_not_present(self) -> None:
        a = assess_log(None)
        assert a.present is False
        assert a.looks_like_run is False
        assert a.clean_run is False

    def test_node_green_is_a_clean_run(self) -> None:
        a = assess_log(_NODE_GREEN)
        assert a.present and a.looks_like_run
        assert a.passed == 1
        assert a.failed == 0
        assert a.has_failures is False
        assert a.clean_run is True

    def test_node_red_is_detected_as_failing(self) -> None:
        a = assess_log(_NODE_RED)
        assert a.failed == 1
        assert a.has_failures is True
        assert a.clean_run is False

    def test_playwright_green_is_a_clean_run(self) -> None:
        a = assess_log(_PW_GREEN)
        assert a.looks_like_run
        assert a.passed == 1
        assert a.has_failures is False
        assert a.clean_run is True

    def test_playwright_red_is_detected_as_failing(self) -> None:
        a = assess_log(_PW_RED)
        assert a.failed == 1
        assert a.has_failures is True
        assert a.clean_run is False

    def test_zero_failed_is_not_a_failure(self) -> None:
        # A summary line "0 failed" must not be misread as a failure — the count is parsed numerically.
        a = assess_log("3 passed\n0 failed\n")
        assert a.failed == 0
        assert a.has_failures is False

    def test_handwritten_note_does_not_look_like_a_run(self) -> None:
        # No runner-shaped tokens (no numeric tally, no TAP/glyph) → the agent faked it.
        a = assess_log("I ran the tests and everything passed, trust me.\n")
        assert a.present is True
        assert a.looks_like_run is False
        assert a.clean_run is False

    def test_minimal_tap_pass_line_counts_as_a_run(self) -> None:
        a = assess_log("ok 1 - it works\n")
        assert a.looks_like_run is True
        assert a.has_failures is False
        assert a.clean_run is True


def _complete(root: Path) -> None:
    """A worktree that satisfies the full framework-agnostic evidence contract with green runs."""
    (root / "package.json").write_text(
        '{\n  "name": "app",\n  "scripts": {\n    "test": "node --test"\n  }\n}\n',
        encoding="utf-8",
    )
    (root / "playwright.config.ts").write_text("export default {};\n", encoding="utf-8")
    ev = root / "test_evidence"
    ev.mkdir()
    (ev / "unit.txt").write_text(_NODE_GREEN, encoding="utf-8")
    (ev / "e2e.txt").write_text(_PW_GREEN, encoding="utf-8")
    (ev / "summary.md").write_text("word " * 160, encoding="utf-8")


class TestScanEvidence:
    def test_complete_green_bundle_is_ok(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        report = scan_evidence(tmp_path)
        assert report.ok is True
        assert report.findings == ()
        assert report.unit.clean_run and report.e2e.clean_run

    def test_missing_project(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "package.json").unlink()
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "missing_project" in kinds

    def test_missing_e2e_harness(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "playwright.config.ts").unlink()
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "missing_e2e_harness" in kinds

    def test_missing_captured_logs(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "unit.txt").unlink()
        (tmp_path / "test_evidence" / "e2e.txt").unlink()
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "missing_unit_log" in kinds
        assert "missing_e2e_log" in kinds

    def test_failing_runs_are_flagged(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "unit.txt").write_text(_NODE_RED, encoding="utf-8")
        (tmp_path / "test_evidence" / "e2e.txt").write_text(_PW_RED, encoding="utf-8")
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "unit_failing" in kinds
        assert "e2e_failing" in kinds

    def test_handwritten_log_is_flagged_as_not_run(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "unit.txt").write_text("all good!\n", encoding="utf-8")
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "unit_not_run" in kinds

    def test_thin_summary_is_flagged(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "summary.md").write_text("too short\n", encoding="utf-8")
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "thin_summary" in kinds

    def test_missing_summary_is_flagged(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "summary.md").unlink()
        kinds = {f.kind for f in scan_evidence(tmp_path).findings}
        assert "missing_summary" in kinds


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: EvidenceScanTool, ctx: object, payload: dict[str, object]) -> object:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


class TestEvidenceScanTool:
    def test_complete_bundle_reports_success(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        result = _run(EvidenceScanTool(), _ctx(tmp_path), {})
        assert result.is_error is False
        assert result.metadata["status"] == "success"
        assert result.metadata["findings"] == []
        assert result.metadata["artifacts"]["unit_ran_green"] is True
        assert result.metadata["artifacts"]["e2e_ran_green"] is True

    def test_incomplete_bundle_warns_with_fixes(self, tmp_path: Path) -> None:
        _complete(tmp_path)
        (tmp_path / "test_evidence" / "e2e.txt").write_text(_PW_RED, encoding="utf-8")
        (tmp_path / "test_evidence" / "summary.md").write_text("thin\n", encoding="utf-8")
        result = _run(EvidenceScanTool(), _ctx(tmp_path), {})
        assert result.is_error is False
        assert result.metadata["status"] == "warning"
        kinds = {f["kind"] for f in result.metadata["findings"]}
        assert "e2e_failing" in kinds
        assert "thin_summary" in kinds
        assert result.metadata["next_actions"]  # every finding carries a concrete fix

    def test_bad_input_is_rejected(self, tmp_path: Path) -> None:
        result = _run(EvidenceScanTool(), _ctx(tmp_path), {"summary_min_words": 0})
        assert result.is_error is True
        assert result.metadata["root_cause"]
        assert result.metadata["safe_retry"]
        assert result.metadata["stop_condition"]


class TestWiring:
    def test_capability_tool_registers_test_evidence_without_a_ledger(self) -> None:
        # It is a pure reader — it must register even in a ledger-free materialization.
        from chorus_harness._factory import _LEDGER_FREE_CAPABILITY_TOOLS, _capability_tool

        assert "evidence_scan" in _LEDGER_FREE_CAPABILITY_TOOLS
        tool = _capability_tool("evidence_scan", None)
        assert isinstance(tool, EvidenceScanTool)

    def test_identity_mapped_for_the_subagent_projection(self) -> None:
        from chorus_harness._factory import dream_tool_names

        assert dream_tool_names(("evidence_scan",)) == ("evidence_scan",)
