"""``test_evidence`` — run the verify commands and collate a durable proof bundle (backend-engineer §10).

The Backend Engineer's load-bearing primitive: it turns "it was tested" from a claim in the transcript
into a set of files on disk. Given the verify commands the engineer discovered for this stack (lint,
typecheck, unit, …), it runs each in the worktree, records a pass/fail *gate* for every one, and writes
a machine-readable ``test_evidence/`` bundle — a ``manifest.json`` a Definition-of-Done can grep, plus a
per-gate log. Stack-agnostic by construction: it runs the commands it is handed, hardcoding no
framework. The bundle's *existence with an all-green verdict* is the proof.

Layered so the logic is model-free and unit-tested: :class:`EvidenceManifest` is a pure verdict over
gate results, :func:`write_bundle` is pure I/O; only :class:`TestEvidenceTool` touches the execution
context, to run the commands.
"""

from __future__ import annotations

import sys
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

from chorus_tools._shared import write_json

GateStatus = Literal["pass", "fail"]

_BUNDLE_DIR = "test_evidence"
_MANIFEST = "manifest.json"
_RED_MANIFEST = "red.json"
_RED_LOG = "red.txt"
_RED_ALLOWED_PREFIXES = (".dream/", ".harness/", "docs/exec-plans/", "test_evidence/")
_RED_ALLOWED_PATHS = frozenset({"TODO.md", "test_plan.json"})
_COMMAND_UNAVAILABLE_MARKERS = (
    "command not found",
    "is not recognized as an internal or external command",
)


def _shell_argv(command: str) -> list[str]:
    if sys.platform == "win32":
        return ["cmd.exe", "/c", command]
    return ["/bin/sh", "-c", command]


@dataclass(frozen=True)
class GateResult:
    """One verify command's outcome — the manifest-facing summary (its full log lives beside it)."""

    name: str
    command: str
    status: GateStatus
    returncode: int


@dataclass(frozen=True)
class EvidenceManifest:
    """The proof bundle's index: every gate plus the single verdict a DoD reads."""

    gates: tuple[GateResult, ...]

    @property
    def verdict(self) -> GateStatus:
        """``pass`` only when every gate passed — a single red gate fails the whole bundle."""
        return "pass" if all(gate.status == "pass" for gate in self.gates) else "fail"

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "gates": [
                {
                    "name": gate.name,
                    "command": gate.command,
                    "status": gate.status,
                    "returncode": gate.returncode,
                }
                for gate in self.gates
            ],
        }


def _log_filename(gate_name: str) -> str:
    """A filesystem-safe ``<gate>.txt`` name for a gate's captured output."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in gate_name)
    return f"{safe or 'gate'}.txt"


def write_bundle(worktree: Path, manifest: EvidenceManifest, outputs: Mapping[str, str]) -> Path:
    """Write the ``test_evidence/`` bundle (the manifest + one log per gate); return its directory."""
    bundle = worktree / _BUNDLE_DIR
    bundle.mkdir(parents=True, exist_ok=True)
    write_json(bundle / _MANIFEST, manifest.to_dict())
    for gate in manifest.gates:
        (bundle / _log_filename(gate.name)).write_text(outputs.get(gate.name, ""), encoding="utf-8")
    return bundle


class GateSpec(BaseModel):
    """One verify command to run, plus the name it is recorded under."""

    name: str = Field(
        min_length=1, description="short gate name, e.g. 'lint' / 'typecheck' / 'unit'"
    )
    command: str = Field(min_length=1, description="the shell command to run, e.g. 'pytest -q'")


class TestEvidenceInput(BaseModel):
    """The gates to run — the verify commands the engineer discovered for this stack."""

    gates: list[GateSpec] = Field(
        min_length=1, description="at least one gate; no gates = no proof"
    )


class TestRedInput(BaseModel):
    """An expected-failing test command and the test files that create the RED state."""

    command: str = Field(min_length=1, description="the test command expected to exit non-zero")
    test_paths: list[str] = Field(
        min_length=1,
        description="worktree-relative test files authored before production changed",
    )
    expected_failure: str = Field(
        min_length=3,
        description=(
            "specific output text proving the missing target behavior caused RED; never use a "
            "generic signal such as 'error' or 'failed'"
        ),
    )


def _normalise_path(raw_path: str) -> str:
    return raw_path.strip().replace("\\", "/").removeprefix("./")


def _looks_like_test(path: str) -> bool:
    candidate = Path(path)
    name = candidate.name.lower()
    parts = {part.lower() for part in candidate.parts}
    return (
        "tests" in parts
        or "test" in parts
        or name.startswith("test_")
        or ".test." in name
        or ".spec." in name
    )


def _red_manifest_path(worktree: Path) -> Path:
    bundle = worktree / _BUNDLE_DIR
    bundle.mkdir(parents=True, exist_ok=True)
    return bundle / _RED_MANIFEST


class TestRedTool(BaseTool):
    """Capture RED only when tests, but no production implementation, changed from Git HEAD."""

    name = "test_red"
    description = (
        "Prove strict TDD chronology before implementation: refuse if the Git delta already contains "
        "production changes; otherwise run an expected-failing test command and write the machine-owned "
        "test_evidence/red.json proof. Call this after writing tests and before production code."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=1200.0)
    input_model = TestRedInput

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = TestRedInput.model_validate(input)
        test_paths = tuple(_normalise_path(path) for path in args.test_paths)
        invalid_test_paths = tuple(path for path in test_paths if not _looks_like_test(path))

        changed_paths: set[str] = set()
        git_error = ""
        for argv in (
            ["git", "diff", "--name-only", "--no-renames", "HEAD"],
            ["git", "diff", "--cached", "--name-only", "--no-renames", "HEAD"],
            ["git", "ls-files", "--others", "--exclude-standard"],
        ):
            result = await ctx.run_subprocess(
                argv, cwd=ctx.working_dir, timeout=self.declaration.timeout_seconds
            )
            raw_code = result.metadata.get("returncode")
            if raw_code != 0:
                git_error = result.content or f"git inspection failed: {' '.join(argv)}"
                break
            changed_paths.update(
                _normalise_path(path) for path in result.content.splitlines() if path.strip()
            )

        allowed_tests = set(test_paths)
        production_paths = tuple(
            sorted(
                path
                for path in changed_paths
                if path not in allowed_tests
                and path not in _RED_ALLOWED_PATHS
                and not path.startswith(_RED_ALLOWED_PREFIXES)
            )
        )
        missing_tests = tuple(
            sorted(
                path
                for path in test_paths
                if path not in changed_paths or not (ctx.working_dir / path).is_file()
            )
        )

        command_output = ""
        returncode: int | None = None
        if not git_error and not invalid_test_paths and not production_paths and not missing_tests:
            run = await ctx.run_subprocess(
                _shell_argv(args.command),
                cwd=ctx.working_dir,
                timeout=self.declaration.timeout_seconds,
            )
            command_output = run.content
            raw_code = run.metadata.get("returncode")
            returncode = raw_code if isinstance(raw_code, int) else -1

        expected_failure_matched = args.expected_failure.casefold() in command_output.casefold()
        command_unavailable = returncode in {126, 127} or any(
            marker in command_output.casefold() for marker in _COMMAND_UNAVAILABLE_MARKERS
        )
        confirmed = (
            not git_error
            and not invalid_test_paths
            and not production_paths
            and not missing_tests
            and returncode is not None
            and not command_unavailable
            and returncode != 0
            and expected_failure_matched
        )
        test_hashes = {
            path: sha256((ctx.working_dir / path).read_bytes()).hexdigest()
            for path in test_paths
            if (ctx.working_dir / path).is_file()
        }
        manifest = {
            "verdict": "red-confirmed" if confirmed else "invalid",
            "command": args.command,
            "returncode": returncode,
            "expected_failure": args.expected_failure,
            "expected_failure_matched": expected_failure_matched,
            "command_unavailable": command_unavailable,
            "test_paths": list(test_paths),
            "test_hashes": test_hashes,
            "production_paths": list(production_paths),
            "invalid_test_paths": list(invalid_test_paths),
            "missing_tests": list(missing_tests),
            "git_error": git_error,
        }
        manifest_path = _red_manifest_path(ctx.working_dir)
        write_json(manifest_path, manifest)
        (manifest_path.parent / _RED_LOG).write_text(command_output, encoding="utf-8")

        if confirmed:
            return ToolResult(
                content="test_evidence/red.json written — verdict red-confirmed.",
                metadata={"verdict": "red-confirmed", "bundle": _BUNDLE_DIR},
            )
        reason = (
            f"production changed before RED: {', '.join(production_paths)}"
            if production_paths
            else f"test command did not execute (exit {returncode})"
            if command_unavailable
            else "the test command did not fail"
            if returncode == 0
            else f"test output did not contain expected failure signal: {args.expected_failure}"
            if returncode is not None and not expected_failure_matched
            else git_error or "test paths were invalid or missing"
        )
        return ToolResult(
            content=f"test_red refused: {reason}.",
            is_error=True,
            metadata={
                "verdict": "invalid",
                "root_cause": reason,
                "safe_retry": "restore production changes, author tests first, then call test_red",
                "stop_condition": "do not claim test-first without a red-confirmed manifest",
            },
        )


class TestEvidenceTool(BaseTool):
    """Run each gate, collate the durable ``test_evidence/`` bundle, and report the verdict."""

    name = "test_evidence"
    description = (
        "Run the project's discovered verify commands (lint / typecheck / unit / …) and collate a "
        "durable, machine-readable test_evidence/ proof bundle in the worktree — so 'it was tested' is "
        "a file on disk. Pass the gates you discovered for this stack; it hardcodes no framework."
    )
    declaration = ToolDeclaration(risk="mutating", tier_required=1, timeout_seconds=1200.0)
    input_model = TestEvidenceInput

    async def execute(self, input: dict[str, Any], ctx: ToolExecutionContext) -> ToolResult:
        args = TestEvidenceInput.model_validate(input)

        results: list[GateResult] = []
        outputs: dict[str, str] = {}
        for gate in args.gates:
            run = await ctx.run_subprocess(
                _shell_argv(gate.command),
                cwd=ctx.working_dir,
                timeout=self.declaration.timeout_seconds,
            )
            raw_code = run.metadata.get("returncode")
            returncode = raw_code if isinstance(raw_code, int) else -1
            status: GateStatus = "pass" if returncode == 0 else "fail"
            results.append(GateResult(gate.name, gate.command, status, returncode))
            outputs[gate.name] = run.content

        manifest = EvidenceManifest(tuple(results))
        write_bundle(ctx.working_dir, manifest, outputs)

        summary = ", ".join(f"{gate.name}:{gate.status}" for gate in manifest.gates)
        metadata: dict[str, Any] = {
            "verdict": manifest.verdict,
            "bundle": _BUNDLE_DIR,
            "summary": f"verdict {manifest.verdict}",
        }
        if manifest.verdict == "fail":
            failed = ", ".join(gate.name for gate in manifest.gates if gate.status == "fail")
            metadata |= {
                "root_cause": f"gate(s) failed: {failed}",
                "safe_retry": "read the failing gate's log under test_evidence/, fix the code, re-run",
                "stop_condition": "do not land while any gate is red",
            }
        return ToolResult(
            content=f"test_evidence/ bundle written — verdict {manifest.verdict} ({summary}).",
            is_error=manifest.verdict == "fail",
            metadata=metadata,
        )


__all__ = [
    "EvidenceManifest",
    "GateResult",
    "GateSpec",
    "TestEvidenceInput",
    "TestEvidenceTool",
    "TestRedInput",
    "TestRedTool",
    "write_bundle",
]
