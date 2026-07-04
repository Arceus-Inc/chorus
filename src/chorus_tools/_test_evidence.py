"""``test_evidence`` — the Frontend Engineer's deterministic pre-done scan of its own test bundle.

A read-only verb that scans a worktree's ``test_evidence/`` bundle and the test suites that produced it,
then returns structured findings: whether the app entry exists, whether a unit suite and an e2e suite are
present, whether each suite's **captured run log** looks like real runner output — and, going beyond the
DoD floor, whether either log shows **failures**, and whether the human-readable summary is substantive.

It is the mechanical half of the "am I actually done?" sandwich — the exact structural analog of
``design_lint`` re-pointed onto the test-evidence substrate: off-token value → missing/absent artifact,
a11y gap → a suite that never ran or ran red. Fully deterministic (no model, no network); the pure
helpers :func:`assess_log` and :func:`scan_evidence` carry the logic and are model-free unit-tested.

Harness contract (agent-harness-construction): a narrow typed input with worktree-relative defaults, a
deterministic output shape (``status`` / ``summary`` / ``findings`` / ``next_actions`` / ``artifacts``),
and an explicit recovery contract (``root_cause`` / ``safe_retry`` / ``stop_condition``) on error paths.
The defaults mirror the Frontend Engineer's evidence contract but are hard-coded here so ``chorus_tools``
never imports ``chorus_employee`` (that would invert the dependency direction).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, ValidationError

FindingKind = Literal[
    "missing_app_entry",
    "missing_unit_tests",
    "missing_e2e_tests",
    "missing_unit_log",
    "unit_not_run",
    "unit_failing",
    "missing_e2e_log",
    "e2e_not_run",
    "e2e_failing",
    "missing_summary",
    "thin_summary",
]

# Output that only a real test runner emits — node:test TAP (``# tests`` / ``# pass`` / ``ok`` /
# ``not ok``), Playwright (``N passed`` / ``Running N tests`` / ``playwright``), and the pass/fail
# glyphs both runners use (incl. the check/cross node prints on a Windows console). Deliberately
# lenient: the point is "a runner ran", not "which runner". Glyphs are \u-escaped to keep the source
# ASCII (no ambiguous-unicode lint).
_RUN_MARKERS = re.compile(
    r"# tests|# pass|# fail|\bnot ok\b|\bok \d|\d+\s+passed|\d+\s+failed|running\s+\d+\s+test|"
    r"playwright|[\u2713\u2714\u221a\u2717\u2718\u00d7]",
    re.IGNORECASE,
)
# A failure the runner names outright — a TAP ``not ok`` line or a red cross glyph. Pass/fail
# *counts* are parsed numerically (below) so "0 failed" never trips this.
_FAILURE_MARKERS = re.compile(r"\bnot ok\b|[\u2717\u2718\u00d7]", re.IGNORECASE)
# Numeric pass/fail tallies across the two runners.
_PASSED = re.compile(r"# pass\s+(\d+)|(\d+)\s+passed", re.IGNORECASE)
_FAILED = re.compile(r"# fail\s+(\d+)|(\d+)\s+failed", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EvidenceSpec:
    """The evidence contract ``test_evidence`` checks against — worktree-relative paths and thresholds.

    Defaults mirror the Frontend Engineer's fixed deliverable, but live here (not imported from the
    employee package) to keep ``chorus_tools`` free of any ``chorus_employee`` dependency.
    """

    app_entry: str = "index.html"
    unit_tests_glob: str = "tests/**/*.test.*"
    e2e_tests_glob: str = "e2e/**/*.spec.*"
    unit_log: str = "test_evidence/unit.txt"
    e2e_log: str = "test_evidence/e2e.txt"
    summary: str = "test_evidence/summary.md"
    summary_min_words: int = 120


@dataclass(frozen=True, slots=True)
class LogAssessment:
    """A deterministic read of one captured run log — was it written, did a runner run, did it go red?"""

    present: bool
    looks_like_run: bool
    passed: int | None
    failed: int | None
    has_failures: bool

    @property
    def clean_run(self) -> bool:
        """True iff a real runner ran to a green result (present, runner-shaped, no failures)."""
        return self.present and self.looks_like_run and not self.has_failures

    @classmethod
    def absent(cls) -> LogAssessment:
        """The reading of a log that was never captured."""
        return cls(present=False, looks_like_run=False, passed=None, failed=None, has_failures=False)


@dataclass(frozen=True, slots=True)
class EvidenceFinding:
    """One deterministic finding — immutable, JSON-serialisable via :meth:`as_dict`."""

    kind: FindingKind
    detail: str
    fix: str

    def as_dict(self) -> dict[str, object]:
        return {"kind": self.kind, "detail": self.detail, "fix": self.fix}


@dataclass(frozen=True, slots=True)
class EvidenceReport:
    """The full deterministic verdict over a worktree's test-evidence bundle."""

    app_entry_present: bool
    unit_tests_present: bool
    e2e_tests_present: bool
    unit: LogAssessment
    e2e: LogAssessment
    summary_present: bool
    summary_words: int
    findings: tuple[EvidenceFinding, ...]

    @property
    def ok(self) -> bool:
        """True iff the bundle is complete and both suites ran green — nothing left to fix."""
        return not self.findings


def _first_int(match: re.Match[str] | None) -> int | None:
    """The first non-``None`` numeric group of a pass/fail match, as an int (or ``None``)."""
    if match is None:
        return None
    for group in match.groups():
        if group is not None:
            return int(group)
    return None


def assess_log(text: str | None) -> LogAssessment:
    """Classify a captured run log: present, runner-shaped, its pass/fail tallies, and if it went red.

    Model-free and deterministic. ``failed`` is parsed numerically so a "0 failed" summary line is never
    read as a failure; a TAP ``not ok`` line or a red ✗ glyph is. ``passed``/``failed`` are ``None`` when
    no tally is printed (some runners only emit ``ok``/``not ok`` lines).
    """
    if text is None:
        return LogAssessment.absent()
    passed = _first_int(_PASSED.search(text))
    failed = _first_int(_FAILED.search(text))
    has_failures = (failed is not None and failed > 0) or bool(_FAILURE_MARKERS.search(text))
    return LogAssessment(
        present=True,
        looks_like_run=bool(_RUN_MARKERS.search(text)),
        passed=passed,
        failed=failed,
        has_failures=has_failures,
    )


def _read_text(path: Path) -> str | None:
    """Read ``path`` as UTF-8, or ``None`` if it isn't a file."""
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def _word_count(text: str | None) -> int:
    """Whitespace-delimited word count (0 for a missing file)."""
    return len(text.split()) if text else 0


def scan_evidence(root: Path, spec: EvidenceSpec | None = None) -> EvidenceReport:
    """Scan ``root`` for the evidence bundle described by ``spec`` and return a deterministic report.

    Does the filesystem IO (globs the suites, reads the logs + summary) and delegates each log's verdict
    to :func:`assess_log`. Findings are emitted in a fixed order (app → unit → e2e → summary) so output
    is stable across runs. Mirrors ``design_lint.lint_design`` in shape.
    """
    spec = spec or EvidenceSpec()
    app_entry_present = (root / spec.app_entry).is_file()
    unit_tests_present = _glob_hit(root, spec.unit_tests_glob)
    e2e_tests_present = _glob_hit(root, spec.e2e_tests_glob)
    unit = assess_log(_read_text(root / spec.unit_log))
    e2e = assess_log(_read_text(root / spec.e2e_log))
    summary_text = _read_text(root / spec.summary)
    summary_present = summary_text is not None
    summary_words = _word_count(summary_text)

    findings: list[EvidenceFinding] = []
    if not app_entry_present:
        findings.append(
            EvidenceFinding(
                "missing_app_entry",
                f"no app entry at {spec.app_entry!r}",
                f"build the working app and save its entry point as {spec.app_entry!r}",
            )
        )
    if not unit_tests_present:
        findings.append(
            EvidenceFinding(
                "missing_unit_tests",
                f"no unit tests match {spec.unit_tests_glob!r}",
                "add a unit suite for the app's logic",
            )
        )
    if not e2e_tests_present:
        findings.append(
            EvidenceFinding(
                "missing_e2e_tests",
                f"no e2e tests match {spec.e2e_tests_glob!r}",
                "add a Playwright e2e spec that drives the real UI",
            )
        )
    findings.extend(_log_findings("unit", unit, spec.unit_log, "node --test"))
    findings.extend(_log_findings("e2e", e2e, spec.e2e_log, "npx playwright test"))
    if not summary_present:
        findings.append(
            EvidenceFinding(
                "missing_summary",
                f"no summary at {spec.summary!r}",
                "write a summary of what was built, how it was tested, and the results",
            )
        )
    elif summary_words < spec.summary_min_words:
        findings.append(
            EvidenceFinding(
                "thin_summary",
                f"summary is {summary_words} words (< {spec.summary_min_words})",
                "expand the summary to cover the build, the test strategy, and the outcomes",
            )
        )

    return EvidenceReport(
        app_entry_present=app_entry_present,
        unit_tests_present=unit_tests_present,
        e2e_tests_present=e2e_tests_present,
        unit=unit,
        e2e=e2e,
        summary_present=summary_present,
        summary_words=summary_words,
        findings=tuple(findings),
    )


def _log_findings(
    label: str, log: LogAssessment, log_path: str, runner: str
) -> tuple[EvidenceFinding, ...]:
    """The findings for one suite's captured log — missing, never-ran, or ran-red (in that order)."""
    missing_kind: FindingKind = "missing_unit_log" if label == "unit" else "missing_e2e_log"
    not_run_kind: FindingKind = "unit_not_run" if label == "unit" else "e2e_not_run"
    failing_kind: FindingKind = "unit_failing" if label == "unit" else "e2e_failing"
    if not log.present:
        return (
            EvidenceFinding(
                missing_kind,
                f"no captured {label} run at {log_path!r}",
                f"run `{runner}` and save its full output to {log_path!r}",
            ),
        )
    if not log.looks_like_run:
        return (
            EvidenceFinding(
                not_run_kind,
                f"{log_path!r} does not look like real {label} runner output",
                f"capture the actual `{runner}` output, not a hand-written note",
            ),
        )
    if log.has_failures:
        tally = f" ({log.failed} failing)" if log.failed else ""
        return (
            EvidenceFinding(
                failing_kind,
                f"the {label} run shows failures{tally}",
                f"fix the code until `{runner}` is green, then re-capture {log_path!r}",
            ),
        )
    return ()


def _glob_hit(root: Path, pattern: str) -> bool:
    """True iff at least one file matches ``pattern`` under ``root`` (files only, not directories)."""
    return any(p.is_file() for p in root.glob(pattern))


class TestEvidenceInput(BaseModel):
    """Typed contract for ``test_evidence`` — every field defaults to the standard bundle layout."""

    app_entry: str = Field(default="index.html", description="the app's entry point")
    unit_tests_glob: str = Field(default="tests/**/*.test.*", description="glob for the unit suite")
    e2e_tests_glob: str = Field(default="e2e/**/*.spec.*", description="glob for the e2e suite")
    unit_log: str = Field(default="test_evidence/unit.txt", description="captured unit-run log")
    e2e_log: str = Field(default="test_evidence/e2e.txt", description="captured e2e-run log")
    summary: str = Field(default="test_evidence/summary.md", description="human-readable summary")
    summary_min_words: int = Field(default=120, ge=1, description="minimum substantive summary length")


class TestEvidenceTool(BaseTool):
    """Deterministically scan the worktree's test-evidence bundle — read-only, no model, no network."""

    name = "test_evidence"
    description = (
        "Deterministically scan your worktree's test-evidence bundle and report what's still missing "
        "or red: the app entry, a unit suite, an e2e suite, the captured unit + e2e run logs (must look "
        "like real runner output AND be green), and a substantive summary. Read-only; returns structured "
        "findings with concrete fixes. Run this BEFORE you declare done — it is the same mechanical check "
        "the Definition of Done enforces, plus failure detection. Args are all optional and default to "
        "the standard bundle layout (index.html, tests/, e2e/, test_evidence/)."
    )
    declaration = ToolDeclaration(risk="safe", tier_required=0, timeout_seconds=15.0)
    input_model = TestEvidenceInput

    async def execute(self, input: dict[str, object], ctx: ToolExecutionContext) -> ToolResult:
        try:
            args = TestEvidenceInput.model_validate(input)
        except ValidationError as exc:
            return _rejected(str(exc))

        spec = EvidenceSpec(
            app_entry=args.app_entry,
            unit_tests_glob=args.unit_tests_glob,
            e2e_tests_glob=args.e2e_tests_glob,
            unit_log=args.unit_log,
            e2e_log=args.e2e_log,
            summary=args.summary,
            summary_min_words=args.summary_min_words,
        )
        report = scan_evidence(ctx.working_dir, spec)
        return _report(report)


def _report(report: EvidenceReport) -> ToolResult:
    if report.ok:
        summary = (
            f"test_evidence: complete — app entry present, unit + e2e suites ran green"
            f"{_tally(report)}, summary is substantive."
        )
        return ToolResult(
            content=summary,
            is_error=False,
            metadata={
                "status": "success",
                "summary": summary,
                "findings": [],
                "next_actions": ["Evidence bundle is complete and green — you may declare done."],
                "artifacts": _artifacts(report),
            },
        )

    summary = f"test_evidence: {len(report.findings)} gap(s) before done{_tally(report)}."
    detail = "\n".join(f"  [{f.kind}] {f.detail}  → {f.fix}" for f in report.findings)
    return ToolResult(
        content=f"{summary}\n{detail}",
        is_error=False,
        metadata={
            "status": "warning",
            "summary": summary,
            "findings": [f.as_dict() for f in report.findings],
            "next_actions": [f.fix for f in report.findings],
            "artifacts": _artifacts(report),
        },
    )


def _tally(report: EvidenceReport) -> str:
    """A compact ``(unit N passed / e2e M passed)`` note when the runners printed tallies."""
    bits: list[str] = []
    if report.unit.passed is not None:
        bits.append(f"unit {report.unit.passed} passed")
    if report.e2e.passed is not None:
        bits.append(f"e2e {report.e2e.passed} passed")
    return f" ({', '.join(bits)})" if bits else ""


def _artifacts(report: EvidenceReport) -> dict[str, object]:
    return {
        "app_entry_present": report.app_entry_present,
        "unit_tests_present": report.unit_tests_present,
        "e2e_tests_present": report.e2e_tests_present,
        "unit_ran_green": report.unit.clean_run,
        "e2e_ran_green": report.e2e.clean_run,
        "summary_words": report.summary_words,
    }


def _rejected(message: str) -> ToolResult:
    return ToolResult(
        content=f"test_evidence rejected: {message}",
        is_error=True,
        metadata={
            "root_cause": message,
            "safe_retry": "call with no args to scan the standard bundle, or override the paths",
            "stop_condition": "the tool input was invalid",
        },
    )


__all__ = [
    "EvidenceFinding",
    "EvidenceReport",
    "EvidenceSpec",
    "LogAssessment",
    "TestEvidenceInput",
    "TestEvidenceTool",
    "assess_log",
    "scan_evidence",
]
