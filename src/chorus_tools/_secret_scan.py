"""``secret_scan`` — mechanically scan the worktree for hardcoded credentials (backend-engineer §09).

The Backend Engineer's safety floor: before landing, prove the diff carries no hardcoded secrets. This
tool scans the worktree's text files against a small, high-signal set of rules (AWS keys, private-key
blocks, provider tokens, and secret-shaped literal assignments) and writes a durable, machine-readable
``security_scan/report.json`` a Definition-of-Done can grep. It never records the raw secret — only the
rule, path, and line — so the report cannot relocate the leak it found.

Layered so the logic is model-free and unit-tested: :func:`scan_text` and :class:`SecretScanReport` are
pure; :func:`write_report` is pure I/O; only :class:`SecretScanTool` touches the execution context, to
discover and read the files.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus_tools._shared import write_json

_REPORT_DIR = "security_scan"
_REPORT = "report.json"
_MAX_BYTES = 1_000_000
_SKIP_PREFIXES = (f"{_REPORT_DIR}/", "test_evidence/", ".git/", ".dream/", ".harness/")

# High-signal, low-false-positive rules: each match is almost certainly a real credential.
_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws-access-key-id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key-block", re.compile(r"-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----")),
    ("github-token", re.compile(r"gh[opsu]_[A-Za-z0-9]{36,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
)

# A secret-shaped name assigned a long string literal — the classic "hardcoded key".
_ASSIGNMENT = re.compile(
    r"""(?ix)
        (?: api[_-]?key | secret | token | password | passwd | access[_-]?key | client[_-]?secret )
        \s* [:=] \s* ["'] (?P<value> [^"']{12,} ) ["']
    """
)
# A literal read from the environment (or config) is the CORRECT pattern — never a finding.
_ENV_CONTEXT = ("environ", "getenv", "process.env", "os.env")
# Obvious non-secrets: placeholders, examples, templated values.
_PLACEHOLDERS = (
    "example",
    "placeholder",
    "changeme",
    "dummy",
    "redacted",
    "your",
    "xxxx",
    "<",
    "${",
)


@dataclass(frozen=True)
class SecretFinding:
    """One suspected credential — the rule it tripped and where, but never the secret itself."""

    rule: str
    path: str
    line: int


def scan_text(path: str, text: str) -> list[SecretFinding]:
    """Scan one file's text; return a finding per suspected credential (the raw value is discarded)."""
    findings: list[SecretFinding] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        findings.extend(
            SecretFinding(rule, path, lineno) for rule, pattern in _RULES if pattern.search(line)
        )
        match = _ASSIGNMENT.search(line)
        if match is None:
            continue
        value, lowered = match.group("value").lower(), line.lower()
        reads_env = any(token in lowered for token in _ENV_CONTEXT)
        is_placeholder = any(token in value for token in _PLACEHOLDERS)
        if not reads_env and not is_placeholder:
            findings.append(SecretFinding("hardcoded-secret", path, lineno))
    return findings


@dataclass(frozen=True)
class SecretScanReport:
    """The scan's durable index: every finding plus the single ``clean`` flag a DoD reads."""

    findings: tuple[SecretFinding, ...]

    def __init__(self, findings: Iterable[SecretFinding]) -> None:
        # Accept any iterable of findings; freeze to a tuple (the dataclass is frozen).
        object.__setattr__(self, "findings", tuple(findings))

    @property
    def clean(self) -> bool:
        """``True`` only when nothing tripped — a single finding fails the scan."""
        return not self.findings

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.clean,
            "findings": [{"rule": f.rule, "path": f.path, "line": f.line} for f in self.findings],
        }


def write_report(worktree: Path, report: SecretScanReport) -> Path:
    """Write ``security_scan/report.json`` into the worktree; return its directory."""
    out = worktree / _REPORT_DIR
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / _REPORT, report.to_dict())
    return out


class SecretScanInput(BaseModel):
    """Optionally scope the scan to specific files; omit to scan the whole worktree."""

    paths: list[str] | None = Field(
        default=None,
        description="specific files to scan; omit to scan the whole worktree (tracked + new, "
        ".gitignore-aware)",
    )


def _scan_one(worktree: Path, rel: str) -> list[SecretFinding]:
    """Read one worktree-relative file and scan it; skip binary/oversized/unreadable files."""
    path = worktree / rel
    try:
        if not path.is_file() or path.stat().st_size > _MAX_BYTES:
            return []
        return scan_text(rel, path.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return []


class SecretScanTool(BaseTool):
    """Scan the worktree for hardcoded credentials and write the durable security_scan/ report."""

    name = "secret_scan"
    description = (
        "Scan the worktree for hardcoded credentials (AWS keys, private keys, provider tokens, "
        "secret-shaped literals) and write a durable, machine-readable security_scan/report.json — so "
        "'no secrets in the diff' is a file on disk, not a claim. Omit paths to scan everything; the "
        "report records the rule + location, never the secret itself."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=120.0)
    input_model = SecretScanInput

    async def _discover(self, ctx: ToolExecutionContext) -> list[str]:
        """List the worktree's scannable files: tracked + new, honouring .gitignore."""
        run = await ctx.run_subprocess(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=ctx.working_dir,
            timeout=60.0,
        )
        code = run.metadata.get("returncode")
        if isinstance(code, int) and code == 0:
            return [line for line in run.content.splitlines() if line.strip()]
        # Not a git repo (or git unavailable): fall back to walking the tree.
        return [
            str(p.relative_to(ctx.working_dir)) for p in ctx.working_dir.rglob("*") if p.is_file()
        ]

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = SecretScanInput.model_validate(input)
        candidates = args.paths if args.paths is not None else await self._discover(ctx)
        rel_paths = [rel for rel in candidates if not rel.startswith(_SKIP_PREFIXES)]

        findings = [finding for rel in rel_paths for finding in _scan_one(ctx.working_dir, rel)]
        report = SecretScanReport(findings)
        write_report(ctx.working_dir, report)

        metadata: dict[str, Any] = {
            "clean": report.clean,
            "report": _REPORT_DIR,
            "summary": "clean" if report.clean else f"{len(findings)} finding(s)",
        }
        if not report.clean:
            hits = ", ".join(f"{f.rule}@{f.path}:{f.line}" for f in report.findings)
            metadata |= {
                "root_cause": f"hardcoded credential(s): {hits}",
                "safe_retry": "move the secret to an environment variable / secret manager, then re-scan",
                "stop_condition": "do not land while any credential is hardcoded",
            }
        return ToolResult(
            content=(
                "security_scan/ report written — clean."
                if report.clean
                else f"security_scan/ report written — {len(findings)} finding(s); remove them before landing."
            ),
            is_error=not report.clean,
            metadata=metadata,
        )


__all__ = [
    "SecretFinding",
    "SecretScanInput",
    "SecretScanReport",
    "SecretScanTool",
    "scan_text",
    "write_report",
]
