"""``recall`` wiring — the factory registers it and every worker role is materialized with it.

Mirrors ``tests/harness/test_factory.py``'s stub-harness pattern: dream's harness build is stubbed so
the role → tool-registry translation is tested without a provider. ``recall`` is rolled out to every
worker role (analyst, backend_engineer, designer, engineer, frontend_engineer, marketer, pm) — manager
and reviewer keep their deliberately minimal, decision-only toolsets and are not included.
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


_RECALL_ROLES = (
    "analyst",
    "backend_engineer",
    "designer",
    "engineer",
    "frontend_engineer",
    "marketer",
    "pm",
)


@pytest.mark.parametrize("role", _RECALL_ROLES)
def test_worker_role_materializes_with_recall(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="emp", name="Emp", role=role))
    names = {t.name for t in captured["registry"].list_tools()}
    assert "recall" in names


def test_recall_is_rooted_at_the_company_memory_dir_not_the_worktree(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    factory, _ = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    assert (tmp_path / "acme" / "memory" / "episodic.db").is_file()


def _tools_line(overlay_toml: str) -> str:
    return next(line for line in overlay_toml.splitlines() if line.startswith("tools"))


def test_recall_is_admitted_to_the_read_only_evaluator_head(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # recall is safe/read-only (like memory_search), so the evaluator head — which keeps a narrowed
    # read-only toolset to verify with — must see it in its `tools = [...]` LIST, not just have the
    # word appear somewhere in the overlay's copied-in brief prose.
    factory, _ = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    evaluator = (mat.working_dir / ".harness" / "roles" / "evaluator.toml").read_text(
        encoding="utf-8"
    )
    assert '"recall"' in _tools_line(evaluator)
