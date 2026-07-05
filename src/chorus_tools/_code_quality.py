"""``code_quality`` — run the stack's format/lint/type checks over the diff (backend-engineer §09).

The §09 "Maintainable" dimension made mechanical: a durable, greppable proof that the shipped code is
clean for its stack, not just that its tests pass. The tool is deliberately **stack-blind** — it runs
exactly the checks it is handed (``{name, command}``) and hardcodes NO linter or type-checker. WHICH
commands to run for a given stack is *know-how*, and know-how lives in the ``verifying-any-stack`` skill
(discover them from the repo's own signals: Makefile / package.json scripts / pyproject / .golangci.yml
/ CI), never in a per-stack ``if python … elif go …`` table in Python (that would be the §03
discover-not-assume violation, in code).

It records each check's *command* so an independent verifier can RE-RUN the exact gate without owning a
tool table, and returns an observation with a recovery contract (root cause / safe retry / stop
condition) — the agent-harness-construction Observation + Error-Recovery pattern.

Layered so the logic is model-free and unit-tested: :class:`QualityReport` is a pure verdict,
:func:`write_report` is pure I/O; only :class:`CodeQualityTool` touches the execution context.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field, model_validator

_REPORT_DIR = "code_quality"
_REPORT = "report.json"

# The three gate KINDS every stack has — a formatter, a linter, and a type/compile check. The tool
# enforces that all three are covered (breadth), never WHICH command implements each (that is the
# stack-specific know-how the verifying-any-stack skill supplies). For a compiled language the build
# IS the types gate; where one tool covers two kinds (e.g. ruff formats and lints) list it under each.
QualityKind = Literal["format", "lint", "types"]
_REQUIRED_KINDS: frozenset[str] = frozenset(get_args(QualityKind))


@dataclass(frozen=True)
class QualityCheck:
    """One quality gate's outcome — its name, kind, the exact command run, pass flag, and detail."""

    name: str
    kind: QualityKind
    command: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class QualityReport:
    """The scan's durable index: every check plus the single ``clean`` flag a DoD reads."""

    checks: tuple[QualityCheck, ...]

    @property
    def clean(self) -> bool:
        """``True`` only when every check passed — one red gate fails the whole report."""
        return all(check.ok for check in self.checks)

    @property
    def first_failure(self) -> QualityCheck | None:
        """The first failing check — the anchor for the recovery hint; ``None`` when clean."""
        return next((check for check in self.checks if not check.ok), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "checks": [
                {
                    "name": c.name,
                    "kind": c.kind,
                    "command": c.command,
                    "ok": c.ok,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


def write_report(worktree: Path, report: QualityReport) -> Path:
    """Write ``code_quality/report.json`` into the worktree; return its directory."""
    out = worktree / _REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / _REPORT).write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
    return out


class QualityCheckSpec(BaseModel):
    """One quality gate to run — its kind, the name it is recorded under, and the command for this stack."""

    name: str = Field(
        min_length=1, description="short gate name, e.g. 'ruff-format' / 'lint' / 'types'"
    )
    kind: QualityKind = Field(
        description="which gate this is: 'format', 'lint', or 'types' — all three must be covered"
    )
    command: str = Field(
        min_length=1,
        description="the exact command for THIS stack, e.g. 'ruff check .' / 'go vet ./...'",
    )


class CodeQualityInput(BaseModel):
    """The quality checks to run — discovered for the stack via the `verifying-any-stack` skill."""

    checks: list[QualityCheckSpec] = Field(
        min_length=1,
        description=(
            "the stack's own commands, covering ALL THREE gate kinds — format, lint, and types. "
            "Discover them via the verifying-any-stack skill; where one tool covers two kinds, list it "
            "under each. A report is only meaningful if it proves the whole trio, not just types."
        ),
    )

    @model_validator(mode="after")
    def _require_all_three_kinds(self) -> CodeQualityInput:
        """Reject a partial report: 'clean' must mean format AND lint AND types all passed, not one."""
        missing = _REQUIRED_KINDS - {check.kind for check in self.checks}
        if missing:
            covered = sorted({check.kind for check in self.checks})
            raise ValueError(
                f"code_quality needs all three gate kinds — format, lint, types. "
                f"You covered {covered}; missing {sorted(missing)}. Discover the missing "
                f"command(s) via the verifying-any-stack skill (for a compiled language the build is "
                f"the types gate; if one tool covers two kinds, e.g. ruff formats and lints, list it "
                f"under each kind)."
            )
        return self


class CodeQualityTool(BaseTool):
    """Run the stack's discovered format/lint/type checks and write the durable code_quality/ report."""

    name = "code_quality"
    description = (
        "Run the stack's format + lint + type-check commands over your code and collate a durable, "
        "machine-readable code_quality/report.json — so 'the code is clean' is a file on disk, not a "
        "claim. This tool is stack-blind: you pass the checks you discovered for this stack (see the "
        "verifying-any-stack skill), and you MUST cover all three gate kinds — format, lint, AND types "
        "— e.g. code_quality(checks=[{'name': 'format', 'kind': 'format', 'command': "
        "'ruff format --check .'}, {'name': 'lint', 'kind': 'lint', 'command': 'ruff check .'}, "
        "{'name': 'types', 'kind': 'types', 'command': 'mypy .'}]). It refuses a partial report so "
        "'clean' can never mean only the types check ran. A red check is a blocker, not a nit."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=600.0)
    input_model = CodeQualityInput

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = CodeQualityInput.model_validate(input)

        results: list[QualityCheck] = []
        for spec in args.checks:
            run = await ctx.run_subprocess(
                ["bash", "-c", spec.command],
                cwd=ctx.working_dir,
                timeout=self.declaration.timeout_seconds,
            )
            code = run.metadata.get("returncode")
            ok = isinstance(code, int) and code == 0
            results.append(
                QualityCheck(
                    name=spec.name,
                    kind=spec.kind,
                    command=spec.command,
                    ok=ok,
                    detail=run.content.strip()[-500:],
                )
            )

        report = QualityReport(tuple(results))
        write_report(ctx.working_dir, report)

        passed = sum(1 for c in report.checks if c.ok)
        summary = f"{passed}/{len(report.checks)} checks passed"
        metadata: dict[str, Any] = {
            "status": "success" if report.clean else "error",
            "summary": summary,
            "report": _REPORT_DIR,
            "next_actions": ["land"]
            if report.clean
            else ["read the failing check's detail", "fix the code", "re-run code_quality"],
        }
        if report.first_failure is not None:
            fail = report.first_failure
            metadata |= {
                "findings": [c.name for c in report.checks if not c.ok],
                "root_cause": f"{fail.name} failed (`{fail.command}`): {fail.detail[-160:]}",
                "safe_retry": "fix the flagged files (add the missing types / clear the lint), then re-run",
                "stop_condition": "do not land while any quality check is red — a lint/type failure is a blocker",
            }
        return ToolResult(
            content=(
                f"code_quality/ report written — clean ({summary})."
                if report.clean
                else f"code_quality/ report written — {summary}; fix the red checks before landing."
            ),
            is_error=not report.clean,
            metadata=metadata,
        )


__all__ = [
    "CodeQualityInput",
    "CodeQualityTool",
    "QualityCheck",
    "QualityCheckSpec",
    "QualityKind",
    "QualityReport",
    "write_report",
]
