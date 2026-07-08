"""``recall`` wiring — the factory registers it and backend_engineer is materialized with it.

Mirrors ``tests/harness/test_factory.py``'s stub-harness pattern: dream's harness build is stubbed so
the role → tool-registry translation is tested without a provider.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

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


def test_backend_engineer_materializes_with_recall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    names = {t.name for t in captured["registry"].list_tools()}
    assert "recall" in names


def test_recall_is_rooted_at_the_company_memory_dir_not_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    assert (tmp_path / "acme" / "memory" / "episodic.db").is_file()
