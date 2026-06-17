"""Materializing an employee into a configured dream harness (spec 06 §2 → dream seam).

The employee's role → tool-name mapping, the per-role overlays that make the *whole* harness run as
the employee, and the wiring of a role-scoped harness into the chat scheduler. dream's harness build
is stubbed so the translation + file writes are tested without a provider.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import pytest

from chorus.ledger import SqliteLedger
from chorus.roles import RoleBeatConfig
from chorus.workforce import Employee
from chorus_cli import _role_chat

pytestmark = pytest.mark.integration


def test_chorus_tools_map_to_dream_builtins_dropping_chorus_only() -> None:
    # engineer's allow-list → dream built-ins (run_command is dream's `bash`)
    assert _role_chat.dream_tool_names(("read_file", "write_file", "run_command", "git")) == (
        "read_file",
        "write_file",
        "bash",
        "git",
    )
    # manager's allow-list → only read_file is a built-in; submit_task/assign_task are chorus tools
    assert _role_chat.dream_tool_names(("read_file", "submit_task", "assign_task")) == ("read_file",)


def test_write_role_overlays_flavours_all_three_dream_roles(tmp_path: Path) -> None:
    config = RoleBeatConfig(
        system_prompt="You implement and ship changes.",
        tools=("read_file", "write_file"),
        permission_mode="acceptEdits",
    )
    _role_chat.write_role_overlays(tmp_path, config)
    for role in ("planner", "generator", "evaluator"):
        overlay = (tmp_path / "roles" / f"{role}.toml").read_text(encoding="utf-8")
        assert "You implement and ship changes." in overlay  # the brief reached every role
        assert 'permission_mode = "acceptEdits"' in overlay  # the employee's posture


def test_build_role_chat_service_resolves_the_role_and_scopes_the_harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        captured: dict[str, Any] = {}

        def _fake_build_harness(**kwargs: Any) -> object:
            captured.update(kwargs)
            return object()

        monkeypatch.setattr(_role_chat.dream, "build_harness", _fake_build_harness)
        service = _role_chat.build_role_chat_service(
            ledger,
            employee_id="ada",
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            render_bus=_role_chat.ChatRenderBus(out=io.StringIO()),
            work_dir=tmp_path,
        )
        assert service.model == "gpt-x"
        # the engineer's harness is scoped to its built-in tools, across the whole loop
        names = [t.name for t in captured["registry"].list_tools()]
        assert set(names) == {"read_file", "write_file", "bash", "git"}
        # the engineer declares no skills → dream's skill loading is off
        assert captured["skills"] is False
        # every other build_harness scalar comes from the engineer's config (not dream's defaults)
        assert captured["model"] == "gpt-x"  # config.model is None → the deployment model
        assert captured["max_turns"] == 12  # the engineer's deeper coding budget
        assert captured["working_memory"] is True  # the engineer keeps a scratchpad
        assert captured["memory"] is True
        assert captured["mcp"] is False and captured["plugins"] is False
        assert captured["wake_model"] is None
        assert captured["env"] is None  # empty role env → no env override
        # and its identity was written as overlays the harness's run_task will read
        assert (tmp_path / "roles" / "generator.toml").exists()
    finally:
        ledger.close()


def test_a_role_that_declares_skills_enables_skill_loading(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from chorus.outcomes import Verifier
    from chorus.roles import RoleManifest, RolePlugin, RoleRegistry

    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ana", name="Ana", role="analyst"))
        skilled = RolePlugin(
            name="analyst",
            manifest=RoleManifest(system_prompt="You analyse.", tools=("read_file",), skills=("data-dive",)),
            dod_generator=lambda intent: Verifier.agent_review(),
            outcome_kind="finding",
        )
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            _role_chat.dream, "build_harness", lambda **kw: captured.update(skills=kw.get("skills"))
        )
        _role_chat.build_role_chat_service(
            ledger,
            employee_id="ana",
            api_key="k",
            base_url="https://x/openai/v1",
            deployment="gpt-x",
            company_id="acme",
            render_bus=_role_chat.ChatRenderBus(out=io.StringIO()),
            work_dir=tmp_path,
            roles=RoleRegistry.from_plugins([skilled]),
        )
        assert captured["skills"] is True  # declaring skills turns dream's skill loading on
    finally:
        ledger.close()
