"""The typed data shapes the harness passes between its stages.

``BenchCase`` is the input (one issue + the human PR that fixed it); ``CandidateSolution``
is what the employee produced (its diff + run metadata); ``EvalResult`` is the verdict.
All are JSON-serialisable so a run can be persisted and re-scored without re-running the
(expensive) employee beat.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class BenchCase:
    """One benchmark instance: an issue, the repo state before the fix, and the human PR.

    Field names mirror SWE-bench (``instance_id`` / ``base_commit`` / ``problem_statement`` /
    ``patch`` / ``test_patch`` / ``FAIL_TO_PASS`` / ``PASS_TO_PASS``) so importing that dataset
    is a straight mapping. ``role`` picks which employee attempts it; ``language`` + ``test_cmd``
    + ``setup_cmd`` drive the objective oracle.
    """

    id: str  # unique instance id (e.g. "astropy__astropy-12345" or "myrepo-issue-42")
    repo: str  # "owner/name" (GitHub) — the clone URL is derived unless clone_url is set
    base_commit: str  # the commit the PR branched from — the repo state BEFORE the fix
    issue_text: str  # the issue / problem statement — submitted verbatim as the task intent

    role: str = (
        "engineer"  # which employee solves it (engineer / frontend_engineer / backend_engineer)
    )
    language: str = "python"  # python | javascript | typescript — selects toolchain defaults

    # --- the human reference fix (for the objective oracle, the judge, and overlap signals) ---
    gold_patch: str = ""  # the PR's SOLUTION diff (never applied to the candidate; reference only)
    test_patch: str = (
        ""  # the PR's TEST diff — applied ON TOP of the candidate for objective scoring
    )
    fail_to_pass: tuple[str, ...] = ()  # tests that were red before the fix and must be green after
    pass_to_pass: tuple[
        str, ...
    ] = ()  # tests that were green and must STAY green (regression guard)

    # --- how to build + run the repo's tests (objective oracle); optional ---
    setup_cmd: str = ""  # e.g. "pip install -e ." / "npm ci" — run once in the prepared repo
    test_cmd: str = ""  # e.g. "pytest -q" / "npm test" — the base command the oracle runs
    clone_url: str = ""  # explicit clone URL; defaults to https://github.com/{repo}.git

    @property
    def effective_clone_url(self) -> str:
        return self.clone_url or f"https://github.com/{self.repo}.git"

    @property
    def has_objective_oracle(self) -> bool:
        """True when the case carries enough to score objectively (a test patch + expected tests)."""
        return bool(self.test_patch and self.fail_to_pass and self.test_cmd)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "repo": self.repo,
            "base_commit": self.base_commit,
            "issue_text": self.issue_text,
            "role": self.role,
            "language": self.language,
            "gold_patch": self.gold_patch,
            "test_patch": self.test_patch,
            "fail_to_pass": list(self.fail_to_pass),
            "pass_to_pass": list(self.pass_to_pass),
            "setup_cmd": self.setup_cmd,
            "test_cmd": self.test_cmd,
            "clone_url": self.clone_url,
        }


@dataclass
class CandidateSolution:
    """What the employee produced for one case — its diff plus how the beat went."""

    case_id: str
    beat_passed: (
        bool  # did the employee's OWN Definition-of-Done floor pass (not the benchmark oracle)
    )
    summary: str
    diff: str  # the candidate patch: `git add -A && git diff --cached <base>` in the worktree
    working_dir: str = ""
    error: str = ""  # non-empty if the beat errored before producing anything
    trace: list[str] = field(default_factory=list)  # observer tool-call lines (for the report)

    @property
    def produced_diff(self) -> bool:
        return bool(self.diff.strip())


@dataclass
class EvalResult:
    """The verdict for one case — the headline ``resolved`` plus the evidence behind it."""

    case_id: str
    resolved: bool  # the headline: did the candidate genuinely fix the issue?
    method: str  # "objective" | "judge" | "none"
    produced_diff: bool = False
    # objective-oracle detail (populated when method == "objective")
    fail_to_pass_passed: int = 0
    fail_to_pass_total: int = 0
    pass_to_pass_passed: int = 0
    pass_to_pass_total: int = 0
    # judge detail (populated when method == "judge")
    judge_score: float | None = None  # 0..1
    judge_verdict: str = ""  # "RESOLVED" | "PARTIAL" | "UNRESOLVED"
    # cheap always-on signals
    files_overlap: float = 0.0  # fraction of gold-patch files the candidate also touched (0..1)
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "resolved": self.resolved,
            "method": self.method,
            "produced_diff": self.produced_diff,
            "fail_to_pass_passed": self.fail_to_pass_passed,
            "fail_to_pass_total": self.fail_to_pass_total,
            "pass_to_pass_passed": self.pass_to_pass_passed,
            "pass_to_pass_total": self.pass_to_pass_total,
            "judge_score": self.judge_score,
            "judge_verdict": self.judge_verdict,
            "files_overlap": round(self.files_overlap, 3),
            "detail": self.detail,
        }
