"""Archetype sweep — every default employee materializes into a faithful dream harness.

Deterministic (no API): asserts each of the five default archetypes resolves through the real
:class:`EmployeeHarnessFactory` into a runner with a role-appropriate config — the structural proof
that the whole workforce is buildable, complementing the live per-archetype runs in examples/.
"""

from __future__ import annotations

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_harness import EmployeeHarnessFactory

pytestmark = pytest.mark.unit


def _factory(tmp_path) -> EmployeeHarnessFactory:
    return EmployeeHarnessFactory(
        api_key="x",
        base_url="http://localhost/v1",
        deployment="model",
        company_id=uid("sweep"),
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
    )


def test_every_default_archetype_materializes(tmp_path) -> None:
    factory = _factory(tmp_path)
    for role in (plugin.name for plugin in default_roles()):
        mat = factory.materialize(Employee(id=f"e-{role}", name=role.title(), role=role))
        assert mat.runner is not None, f"{role} produced no runner"
        assert mat.config.tools, f"{role} has an empty toolset"
        assert mat.config.system_prompt, f"{role} has no brief"


def test_backend_engineer_can_run_commands(tmp_path) -> None:
    mat = _factory(tmp_path).materialize(Employee(id=uid("e"), name="E", role="backend_engineer"))
    assert "run_command" in mat.config.tools
    assert mat.config.sandbox == "unrestricted"


def test_analyst_brings_tools_skills_and_subagents(tmp_path) -> None:
    mat = _factory(tmp_path).materialize(Employee(id=uid("a"), name="A", role="analyst"))
    assert {"warehouse_query", "notebook_run", "chart_render", "repo_search"} <= set(
        mat.config.tools
    )
    assert mat.config.skills_root is not None
    assert {sa.name for sa in mat.config.subagents} >= {"data", "critic"}
