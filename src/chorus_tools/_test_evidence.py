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

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from dream.contracts.tool import ToolResult
from dream.tools._base import BaseTool, ToolDeclaration
from dream.tools._context import ToolExecutionContext
from pydantic import BaseModel, Field

GateStatus = Literal["pass", "fail"]

_BUNDLE_DIR = "test_evidence"
_MANIFEST = "manifest.json"


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
    (bundle / _MANIFEST).write_text(
        json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8"
    )
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
                ["bash", "-c", gate.command],
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
    "write_bundle",
]
