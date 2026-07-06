"""Building the chat beat service over the org harness factory (spec 06 §2).

The role → harness materialization itself is tested in ``tests/harness/test_factory.py``; here we test
the chat front-end's *wiring*: resolve the employee, hand the factory's materialized harness to a
scheduler with the render bus, and surface the worktree + config on the :class:`ChatBeatService`.
"""

from __future__ import annotations

import io
import subprocess
from pathlib import Path
from typing import Any

import pytest

from chorus.errors import UnknownEmployee
from chorus.ledger import SqliteLedger
from chorus.workforce import Employee
from chorus_cli import _role_chat
from chorus_cli._chat import ChatBeatService
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration


def _stub_build_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub dream's harness build (the factory owns the import) so no provider is needed."""
    monkeypatch.setattr(_factory_mod.dream, "build_harness", lambda **kw: object())


def _service(ledger: SqliteLedger, *, employee_id: str = "ada", **kwargs: Any) -> ChatBeatService:
    return _role_chat.build_role_chat_service(
        ledger,
        employee_id=employee_id,
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        render_bus=_role_chat.ChatRenderBus(out=io.StringIO()),
        **kwargs,
    )


def test_unknown_employee_raises(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _stub_build_harness(monkeypatch)
    ledger = SqliteLedger.open(":memory:")
    try:
        with pytest.raises(UnknownEmployee):
            _service(ledger, employee_id="ghost", work_root=tmp_path)
    finally:
        ledger.close()


def test_service_surfaces_the_materialized_worktree_and_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_harness(monkeypatch)
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        service = _service(ledger, work_root=tmp_path)
        assert service.model == "gpt-x"
        # the chat service runs in the employee's branch-isolated worktree (shared with tick)
        assert service.working_dir == str(tmp_path / "acme" / "worktrees" / "ada")
        assert service.workspace is not None  # /merge can integrate it
        # /config reads the resolved role spec off the service
        assert "memory_search" in service.harness_spec.tools
        assert "working_memory_write" in service.harness_spec.tools
        assert service.harness_spec.permission_mode == "acceptEdits"
    finally:
        ledger.close()


def test_chat_wires_the_role_registry_so_tasks_inherit_the_role_dod(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_harness(monkeypatch)
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        captured: dict[str, Any] = {}
        real_scheduler = _role_chat.Scheduler

        def _capture(**kw: Any) -> object:
            captured.update(kw)
            return real_scheduler(**kw)

        monkeypatch.setattr(_role_chat, "Scheduler", _capture)
        _service(ledger, work_root=tmp_path)
        # the scheduler is handed the role registry → a chat task inherits the engineer's DoD at intake
        assert captured["roles"] is not None
        assert "engineer" in captured["roles"]
    finally:
        ledger.close()


def test_seed_makes_the_employee_branch_off_real_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _stub_build_harness(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(
        ["git", "-C", str(source), "init", "-b", "trunk"], check=True, capture_output=True
    )
    (source / "app.py").write_text("print('real')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(source), "add", "-A"], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=u",
            "-c",
            "user.email=u@x",
            "commit",
            "-m",
            "i",
        ],
        check=True,
        capture_output=True,
    )

    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        service = _service(ledger, work_root=tmp_path / "ws", seed=source)
        # the engineer's worktree starts from the seeded codebase, not a blank tree
        assert (Path(service.working_dir) / "app.py").read_text(
            encoding="utf-8"
        ) == "print('real')\n"
    finally:
        ledger.close()
