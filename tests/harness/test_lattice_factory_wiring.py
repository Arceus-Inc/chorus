"""``lattice`` wiring — factory registers tools for worker roles."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod

pytestmark = pytest.mark.integration

# M8 canonicalized professions: the generic "engineer" role folded into backend_engineer.
_LATTICE_ROLES = (
    "analyst",
    "backend_engineer",
    "designer",
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
def test_worker_role_materializes_lattice_skills(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    mat = factory.materialize(Employee(id=uid("emp"), name="Emp", role=role))
    for skill in ("lattice-context", "lattice-consolidate"):
        path = mat.working_dir / ".harness" / "skills" / skill / "SKILL.md"
        assert path.is_file(), f"{role} missing materialized {skill}"
    assert captured["skills"] is True


@pytest.mark.parametrize("role", _LATTICE_ROLES)
def test_worker_role_materializes_with_lattice_tools(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, role: str
) -> None:
    factory, captured = _factory(monkeypatch, tmp_path)
    factory.materialize(Employee(id=uid("emp"), name="Emp", role=role))
    names = {t.name for t in captured["registry"].list_tools()}
    assert {"lattice_context", "lattice_packet", "lattice_apply", "skill_manage"}.issubset(names)


def test_lattice_failure_leaves_observable_breadcrumb(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An advisory lattice failure never blocks the beat — but it must never be invisible either.

    A broken lattice (corrupt DB, refactored dep) previously meant consolidation silently stopped
    forever; now materialize leaves .harness/lattice-error.json as a greppable breadcrumb.
    """
    factory, _ = _factory(monkeypatch, tmp_path)
    monkeypatch.setattr(
        _factory_mod,
        "build_lattice_for_chorus",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("lattice db corrupt")),
    )
    mat = factory.materialize(Employee(id=uid("emp"), name="Emp", role="backend_engineer"))

    breadcrumb = mat.working_dir / ".harness" / "lattice-error.json"
    assert breadcrumb.is_file()
    payload = breadcrumb.read_text(encoding="utf-8")
    assert "materialize." in payload  # site recorded (last failing site wins)
    assert "lattice db corrupt" in payload
