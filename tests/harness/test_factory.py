"""EmployeeHarnessFactory — the org's one role-faithful materializer (spec 06 §2 → dream seam).

dream's harness build is stubbed so the role → harness translation is tested without a provider; the
worktree side-effects run on real git in a temp dir.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chorus.heartbeat import BeatRunner
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    factory = _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
    )
    return factory, captured


def test_engineer_materializes_a_writable_harness_in_its_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="ada", name="Ada", role="engineer"))
    # the engineer works confined to its own branch-isolated worktree under the org root
    assert mat.working_dir == tmp_path / "acme" / "worktrees" / "ada"
    assert mat.workspace is not None
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {"read_file", "write_file", "bash", "git"}
    assert mat.config.permission_mode == "acceptEdits"
    assert captured["max_turns"] == 12  # the engine scalars come from the role too


def test_reviewer_materializes_a_read_only_harness(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="rob", name="Rob", role="reviewer"))
    # the headline win: a reviewer is read-only EVERYWHERE — not just in chat
    names = {t.name for t in captured["registry"].list_tools()}
    assert names == {"read_file"}
    assert mat.config.permission_mode == "plan"


def test_runner_for_is_a_beat_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    runner = factory.runner_for(Employee(id="ada", name="Ada", role="engineer"))
    assert isinstance(runner, BeatRunner)  # the scheduler dispatches through this


def test_unregistered_role_fails_closed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="not a registered role"):
        factory.materialize(Employee(id="x", name="X", role="ghost"))
