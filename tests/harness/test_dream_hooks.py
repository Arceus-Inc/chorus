"""Unit tests for Chorus dream hooks (dangerous veto + evidence continue + forge)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dream.contracts.hook import HookEvent

from chorus_harness._dream_hooks import (
    DangerousToolVetoHook,
    EvidenceContinueHook,
    EvidenceForgeVetoHook,
    EvidenceRequirement,
    ProtectedEvidencePath,
    StopHookPhase,
    StopHookRole,
)

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
async def test_forge_veto_blocks_parent_test_plan_write() -> None:
    hook = EvidenceForgeVetoHook(
        (ProtectedEvidencePath("test_plan.json", "test_author"),)
    )
    result = await hook(
        HookEvent.PRE_TOOL_USE,
        {
            "tool_name": "write_file",
            "tool_input": {"path": "test_plan.json", "content": '{"authored": true}'},
            "subagent_name": None,
        },
    )
    assert result.blocked is True
    assert "test_author" in (result.feedback or "")
    assert "spawn_subagent" in (result.feedback or "")


@pytest.mark.asyncio
async def test_forge_veto_allows_child_specialist() -> None:
    hook = EvidenceForgeVetoHook(
        (ProtectedEvidencePath("test_plan.json", "test_author"),)
    )
    result = await hook(
        HookEvent.PRE_TOOL_USE,
        {
            "tool_name": "write_file",
            "tool_input": {"path": "test_plan.json", "content": "{}"},
            "subagent_name": "test_author",
        },
    )
    assert result.blocked is False


@pytest.mark.asyncio
async def test_forge_veto_blocks_evidence_dir() -> None:
    hook = EvidenceForgeVetoHook(
        (ProtectedEvidencePath("test_plan.json", "test_author"),)
    )
    result = await hook(
        HookEvent.PRE_TOOL_USE,
        {
            "tool_name": "write_file",
            "tool_input": {"path": ".harness/subagent-evidence/test_author.json"},
        },
    )
    assert result.blocked is True


@pytest.mark.asyncio
async def test_evidence_continue_when_missing(tmp_path: Path) -> None:
    hook = EvidenceContinueHook(
        (EvidenceRequirement("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(
        HookEvent.STOP,
        {"phase": StopHookPhase.PRE_SEAL, "verify_nudges": 0, "role": StopHookRole.GENERATOR},
    )
    assert result.continue_message is not None
    assert "code_reviewer" in result.continue_message
    assert "spawn_subagent" in result.continue_message


@pytest.mark.asyncio
async def test_evidence_continue_skips_planner(tmp_path: Path) -> None:
    hook = EvidenceContinueHook(
        (EvidenceRequirement("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(HookEvent.STOP, {"phase": StopHookPhase.PRE_SEAL, "role": "planner"})
    assert result.continue_message is None


@pytest.mark.asyncio
async def test_evidence_continue_quiet_when_present(tmp_path: Path) -> None:
    path = tmp_path / "review_verdict.json"
    path.write_text(json.dumps({"cleared": True}), encoding="utf-8")
    hook = EvidenceContinueHook(
        (EvidenceRequirement("code_reviewer", "review_verdict.json", {"cleared": True}),),
        working_dir=tmp_path,
    )
    result = await hook(
        HookEvent.STOP, {"phase": StopHookPhase.PRE_SEAL, "role": StopHookRole.GENERATOR}
    )
    assert result.continue_message is None
