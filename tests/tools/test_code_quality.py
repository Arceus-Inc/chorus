"""Unit tests for the ``code_quality`` tool (backend-engineer §09 Maintainable dimension).

The tool is STACK-BLIND: it runs the checks it is handed (the agent discovers them for its stack via
the ``verifying-any-stack`` skill), collates a durable ``code_quality/report.json``, and returns an
observation with a recovery contract. It hardcodes no linter/type-checker command — that knowledge
lives in the skill, not in Python. It DOES enforce *breadth*: every report must cover all three gate
kinds (format + lint + types), so a green report can never mean "only the types check ran".
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dream.contracts.tool import ToolResult
from pydantic import ValidationError

from chorus_tools._code_quality import (
    CodeQualityInput,
    CodeQualityTool,
    QualityCheck,
    QualityCheckSpec,
    QualityKind,
    QualityReport,
    write_report,
)

pytestmark = pytest.mark.unit


def _check(name: str, ok: bool, kind: QualityKind = "lint") -> QualityCheck:
    return QualityCheck(name=name, kind=kind, command=f"run-{name}", ok=ok, detail="")


def _all_three(command: str = "true") -> list[dict[str, str]]:
    """The minimum breadth every real call must carry: one check per gate kind."""
    return [
        {"name": "format", "kind": "format", "command": command},
        {"name": "lint", "kind": "lint", "command": command},
        {"name": "types", "kind": "types", "command": command},
    ]


# --------------------------------------------------------------------- the pure report model


def test_report_is_clean_only_when_every_check_passes() -> None:
    assert QualityReport(checks=(_check("lint", True), _check("types", True))).clean is True
    assert QualityReport(checks=(_check("lint", True), _check("types", False))).clean is False


def test_report_names_the_first_failure_for_the_recovery_hint() -> None:
    report = QualityReport(checks=(_check("format", True), _check("types", False)))
    assert report.first_failure is not None
    assert report.first_failure.name == "types"


def test_clean_report_has_no_first_failure() -> None:
    assert QualityReport(checks=(_check("lint", True),)).first_failure is None


def test_to_dict_records_each_check_its_kind_and_its_command() -> None:
    # The command is recorded so an independent verifier can RE-RUN it without hardcoding the tool set;
    # the kind is recorded so a reader can see the report covers all three gates.
    payload = QualityReport(checks=(_check("lint", True, kind="lint"),)).to_dict()
    assert payload["clean"] is True
    assert payload["checks"][0] == {
        "name": "lint",
        "kind": "lint",
        "command": "run-lint",
        "ok": True,
        "detail": "",
    }


def test_report_is_frozen() -> None:
    report = QualityReport(checks=())
    with pytest.raises((AttributeError, TypeError)):
        report.checks = ()  # type: ignore[misc]


# --------------------------------------------------------------------- breadth: all three kinds


def test_input_requires_all_three_gate_kinds() -> None:
    # A types-only call is exactly last run's gap — the tool must refuse it so 'clean' means the trio.
    with pytest.raises(ValidationError) as exc:
        CodeQualityInput(checks=[QualityCheckSpec(name="types", kind="types", command="mypy .")])
    message = str(exc.value)
    assert "format" in message and "lint" in message  # names the missing kinds


def test_input_accepts_a_call_covering_format_lint_and_types() -> None:
    args = CodeQualityInput(
        checks=[
            QualityCheckSpec(name="fmt", kind="format", command="ruff format --check ."),
            QualityCheckSpec(name="lint", kind="lint", command="ruff check ."),
            QualityCheckSpec(name="types", kind="types", command="mypy ."),
        ]
    )
    assert {c.kind for c in args.checks} == {"format", "lint", "types"}


def test_input_allows_one_tool_to_cover_two_kinds() -> None:
    # A stack where the formatter and linter are the same tool (e.g. ruff) lists it under each kind —
    # breadth is about the gate KINDS covered, never about distinct commands.
    args = CodeQualityInput(
        checks=[
            QualityCheckSpec(name="ruff-format", kind="format", command="ruff format --check ."),
            QualityCheckSpec(name="ruff-lint", kind="lint", command="ruff check ."),
            QualityCheckSpec(name="types", kind="types", command="mypy ."),
        ]
    )
    assert len(args.checks) == 3


def test_input_rejects_an_unknown_kind() -> None:
    with pytest.raises(ValidationError):
        QualityCheckSpec(name="x", kind="security", command="true")  # type: ignore[arg-type]


# --------------------------------------------------------------------- the report writer


def test_write_report_writes_a_parseable_json(tmp_path: Path) -> None:
    out = write_report(tmp_path, QualityReport(checks=(_check("lint", True),)))
    assert out == tmp_path / "code_quality"
    parsed = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert parsed["clean"] is True


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


def _run(tool: CodeQualityTool, payload: dict[str, object], ctx: object) -> ToolResult:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


def test_tool_writes_a_clean_report_when_every_check_passes(tmp_path: Path) -> None:
    result = _run(CodeQualityTool(), {"checks": _all_three("true")}, _ctx(tmp_path))
    assert result.is_error is False
    parsed = json.loads((tmp_path / "code_quality" / "report.json").read_text(encoding="utf-8"))
    assert parsed["clean"] is True
    assert {c["kind"] for c in parsed["checks"]} == {"format", "lint", "types"}


def test_tool_flags_error_with_a_recovery_contract_on_a_failing_check(tmp_path: Path) -> None:
    checks = _all_three("true")
    checks[2]["command"] = "false"  # the types gate fails
    result = _run(CodeQualityTool(), {"checks": checks}, _ctx(tmp_path))
    assert result.is_error is True  # a red quality check is a real, retryable error
    # The observation carries the recovery contract (root cause / safe retry / stop condition).
    assert "root_cause" in result.metadata
    assert "safe_retry" in result.metadata
    assert "stop_condition" in result.metadata
    assert "types" in str(result.metadata["root_cause"])
    parsed = json.loads((tmp_path / "code_quality" / "report.json").read_text(encoding="utf-8"))
    assert parsed["clean"] is False


def test_tool_hardcodes_no_stack_commands(tmp_path: Path) -> None:
    # It runs exactly what it was handed — the command flows through to the recorded report.
    checks = _all_three("true")
    checks[1]["command"] = "echo custom"
    _run(CodeQualityTool(), {"checks": checks}, _ctx(tmp_path))
    parsed = json.loads((tmp_path / "code_quality" / "report.json").read_text(encoding="utf-8"))
    assert parsed["checks"][1]["command"] == "echo custom"


def test_tool_rejects_a_report_missing_a_gate_kind(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _run(
            CodeQualityTool(),
            {"checks": [{"name": "lint", "kind": "lint", "command": "true"}]},
            _ctx(tmp_path),
        )


def test_tool_rejects_an_empty_check_list(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _run(CodeQualityTool(), {"checks": []}, _ctx(tmp_path))
