"""Unit tests for Chorus dream hooks (dangerous veto + evidence continue)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dream.contracts.hook import HookEvent

from chorus_harness._dream_hooks import DangerousToolVetoHook, EvidenceContinueHook

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_dangerous_tool_veto_blocks_rm_rf() -> None:
    hook = DangerousToolVetoHook()
    result = await hook(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "run_command", "tool_input": {"command": "rm -rf /"}},
    )
    assert result.blocked is True
    assert result.feedback


@pytest.mark.asyncio
async def test_dangerous_tool_veto_allows_pytest() -> None:
    hook = DangerousToolVetoHook()
    result = await hook(
        HookEvent.PRE_TOOL_USE,
        {"tool_name": "run_command", "tool_input": {"command": "pytest -q"}},
    )
    assert result.blocked is False


@pytest.mark.asyncio
async def test_evidence_continue_when_missing(tmp_path: Path) -> None:
    hook = EvidenceContinueHook(
        (("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(
        HookEvent.STOP, {"phase": "pre_seal", "verify_nudges": 0, "role": "generator"}
    )
    assert result.continue_message is not None
    assert "code_reviewer" in result.continue_message


@pytest.mark.asyncio
async def test_evidence_continue_skips_planner(tmp_path: Path) -> None:
    hook = EvidenceContinueHook(
        (("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(HookEvent.STOP, {"phase": "pre_seal", "role": "planner"})
    assert result.continue_message is None


@pytest.mark.asyncio
async def test_evidence_continue_quiet_when_present(tmp_path: Path) -> None:
    path = tmp_path / "review_verdict.json"
    path.write_text(json.dumps({"cleared": True}), encoding="utf-8")
    hook = EvidenceContinueHook(
        (("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(HookEvent.STOP, {"phase": "pre_seal", "role": "generator"})
    assert result.continue_message is None
