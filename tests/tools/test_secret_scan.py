"""Unit tests for the Backend Engineer's ``secret_scan`` primitive (backend-engineer spec §09 safety).

The safety floor: mechanically scan the worktree for hardcoded credentials and record a durable,
machine-readable ``security_scan/report.json`` a Definition-of-Done can gate on. The detection rules
and report model are pure (model-free); the tool reads real files through the execution context. The
report never stores the raw secret — only the rule, path, and line — so it can't relocate the leak.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from dream.contracts.tool import ToolResult
from pydantic import ValidationError

from chorus_tools._secret_scan import (
    SecretScanReport,
    SecretScanTool,
    scan_text,
    write_report,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------- the pure detection rules


def test_flags_an_aws_access_key_id() -> None:
    findings = scan_text("config.py", 'API_KEY = "AKIAIOSFODNN7EXAMPLE"\n')
    assert any(f.rule == "aws-access-key-id" for f in findings)
    assert findings[0].path == "config.py"
    assert findings[0].line == 1


def test_flags_a_private_key_block() -> None:
    findings = scan_text("id_rsa", "-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n")
    assert any(f.rule == "private-key-block" for f in findings)


def test_flags_a_hardcoded_secret_assignment() -> None:
    findings = scan_text("app.py", 'password = "s3cr3tVALUE12345"\n')
    assert any(f.rule == "hardcoded-secret" for f in findings)


def test_ignores_a_value_read_from_the_environment() -> None:
    # Reading a secret from the environment is the CORRECT pattern — never a finding.
    clean = 'api_key = os.environ["SOME_LONG_ENV_VAR_NAME_HERE"]\n'
    assert scan_text("app.py", clean) == []


def test_ignores_an_obvious_placeholder() -> None:
    assert scan_text("app.py", 'api_key = "your-api-key-here-example"\n') == []


def test_clean_text_yields_no_findings() -> None:
    assert scan_text("app.py", "def add(a: int, b: int) -> int:\n    return a + b\n") == []


# --------------------------------------------------------------------- the report model


def test_report_is_clean_only_with_no_findings() -> None:
    assert SecretScanReport(findings=()).clean is True
    dirty = SecretScanReport(findings=scan_text("c.py", 'k = "AKIAIOSFODNN7EXAMPLE"\n'))
    assert dirty.clean is False


def test_report_to_dict_never_carries_the_raw_secret() -> None:
    report = SecretScanReport(findings=scan_text("config.py", 'API_KEY = "AKIAIOSFODNN7EXAMPLE"\n'))
    payload = report.to_dict()
    assert payload["clean"] is False
    assert payload["findings"][0]["rule"] == "aws-access-key-id"
    assert "AKIAIOSFODNN7EXAMPLE" not in json.dumps(payload)  # the leak is not relocated


# --------------------------------------------------------------------- the report writer


def test_write_report_writes_a_parseable_json_report(tmp_path: Path) -> None:
    report = SecretScanReport(findings=())
    out = write_report(tmp_path, report)
    assert out == tmp_path / "security_scan"
    parsed = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert parsed == {"clean": True, "findings": []}


# --------------------------------------------------------------------- the tool (real files)


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _run(tool: SecretScanTool, payload: dict[str, object], ctx: object) -> ToolResult:
    return asyncio.run(tool.execute(payload, ctx))  # type: ignore[arg-type]


def test_tool_reports_clean_on_a_safe_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text('key = os.environ["API_KEY"]\n', encoding="utf-8")
    result = _run(SecretScanTool(), {"paths": ["app.py"]}, _ctx(tmp_path))

    assert result.is_error is False
    parsed = json.loads((tmp_path / "security_scan" / "report.json").read_text(encoding="utf-8"))
    assert parsed["clean"] is True


def test_tool_flags_error_and_records_the_finding_on_a_leak(tmp_path: Path) -> None:
    (tmp_path / "config.py").write_text('API_KEY = "AKIAIOSFODNN7EXAMPLE"\n', encoding="utf-8")
    result = _run(SecretScanTool(), {"paths": ["config.py"]}, _ctx(tmp_path))

    assert result.is_error is True  # a hardcoded secret is a real, retryable error
    parsed = json.loads((tmp_path / "security_scan" / "report.json").read_text(encoding="utf-8"))
    assert parsed["clean"] is False
    assert parsed["findings"][0]["rule"] == "aws-access-key-id"


def test_tool_does_not_scan_its_own_report(tmp_path: Path) -> None:
    # A prior report must not make a later scan dirty (no self-referential false positive).
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    _run(SecretScanTool(), {}, _ctx(tmp_path))  # first pass writes security_scan/report.json
    result = _run(SecretScanTool(), {}, _ctx(tmp_path))  # second pass must stay clean
    assert result.is_error is False


def test_tool_rejects_a_paths_value_that_is_a_bare_string(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        _run(SecretScanTool(), {"paths": "app.py"}, _ctx(tmp_path))
