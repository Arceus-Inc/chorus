"""``lattice`` wiring — factory registers tools for worker roles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration

_LATTICE_ROLES = (
    "analyst",
    "backend_engineer",
    "designer",
    "engineer",
    "frontend_engineer",
    "marketer",
    "pm",
)


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


@pytest.mark.parametrize("role", _LATTICE_ROLES)
def test_worker_role_materializes_with_lattice_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id="emp", name="Emp", role=role))
    names = {t.name for t in captured["registry"].list_tools()}
    assert {"lattice_context", "lattice_packet", "lattice_apply"}.issubset(names)
