"""Unit tests for the Backend Engineer's ``test_evidence`` primitive (backend-engineer spec §10).

The load-bearing proof primitive: run the project's verify commands and collate a durable,
machine-readable ``test_evidence/`` bundle into the worktree — so "it was tested" is a file on disk,
not a claim in the transcript. The manifest model and bundle writer are pure (model-free); the tool
runs real but trivial commands (``true`` / ``false`` / ``echo``) through the execution context.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dream.contracts.tool import ToolResult
from pydantic import ValidationError

from chorus_tools._test_evidence import (
    EvidenceManifest,
    GateResult,
    TestEvidenceTool,
    write_bundle,
)

pytestmark = pytest.mark.unit


def _gate(name: str, status: str, returncode: int) -> GateResult:
    return GateResult(name=name, command=f"run-{name}", status=status, returncode=returncode)  # type: ignore[arg-type]


# --------------------------------------------------------------------- the pure manifest model


def test_verdict_passes_only_when_every_gate_passes() -> None:
    manifest = EvidenceManifest(gates=(_gate("lint", "pass", 0), _gate("unit", "pass", 0)))
    assert manifest.verdict == "pass"


def test_verdict_fails_when_any_gate_fails() -> None:
    manifest = EvidenceManifest(gates=(_gate("lint", "pass", 0), _gate("unit", "fail", 1)))
    assert manifest.verdict == "fail"


def test_to_dict_carries_the_verdict_and_every_gate() -> None:
    manifest = EvidenceManifest(gates=(_gate("unit", "pass", 0),))
    assert manifest.to_dict() == {
        "verdict": "pass",
        "gates": [{"name": "unit", "command": "run-unit", "status": "pass", "returncode": 0}],
    }


def test_manifest_is_frozen() -> None:
    manifest = EvidenceManifest(gates=())
    with pytest.raises((AttributeError, TypeError)):
        manifest.gates = ()  # type: ignore[misc]


# --------------------------------------------------------------------- the bundle writer


def test_write_bundle_writes_a_parseable_manifest_and_per_gate_logs(tmp_path: Path) -> None:
    manifest = EvidenceManifest(gates=(_gate("unit", "pass", 0), _gate("lint", "fail", 1)))
    bundle = write_bundle(tmp_path, manifest, {"unit": "2 passed", "lint": "E501 line too long"})

    assert bundle == tmp_path / "test_evidence"
    parsed = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert parsed["verdict"] == "fail"
    assert (bundle / "unit.txt").read_text(encoding="utf-8") == "2 passed"
    assert (bundle / "lint.txt").read_text(encoding="utf-8") == "E501 line too long"


# --------------------------------------------------------------------- the tool (real trivial commands)


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: TestEvidenceTool, payload: dict[str, object], ctx: object) -> ToolResult:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


def test_tool_writes_a_green_bundle_when_all_gates_pass(tmp_path: Path) -> None:
    result = _run(
        TestEvidenceTool(), {"gates": [{"name": "ok", "command": "true"}]}, _ctx(tmp_path)
    )

    assert result.is_error is False
    assert result.metadata["verdict"] == "pass"
    manifest = json.loads(
        (tmp_path / "test_evidence" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["verdict"] == "pass"
    assert manifest["gates"][0]["returncode"] == 0


def test_tool_flags_error_but_still_lands_the_bundle_on_a_failing_gate(tmp_path: Path) -> None:
    result = _run(
        TestEvidenceTool(),
        {"gates": [{"name": "ok", "command": "true"}, {"name": "unit", "command": "false"}]},
        _ctx(tmp_path),
    )

    assert result.is_error is True  # a failing gate is a real, retryable error
    assert result.metadata["verdict"] == "fail"
    # The bundle lands regardless — a red gate is itself the evidence.
    manifest = json.loads(
        (tmp_path / "test_evidence" / "manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["verdict"] == "fail"


def test_tool_captures_gate_output_into_the_bundle(tmp_path: Path) -> None:
    _run(
        TestEvidenceTool(),
        {"gates": [{"name": "echo", "command": "echo hi-evidence"}]},
        _ctx(tmp_path),
    )

    assert "hi-evidence" in (tmp_path / "test_evidence" / "echo.txt").read_text(encoding="utf-8")


def test_tool_rejects_an_empty_gate_list(tmp_path: Path) -> None:
    # No gates = no proof; the input must carry at least one command to run.
    with pytest.raises(ValidationError):
        _run(TestEvidenceTool(), {"gates": []}, _ctx(tmp_path))
