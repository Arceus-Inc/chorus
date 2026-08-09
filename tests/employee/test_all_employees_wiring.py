"""Cross-cutting wiring invariants every employee must satisfy (post multi-employee merge).

Two things the merge has to preserve across ALL employees:
1. **todo_write** — the durable cross-beat checklist (TODO.md) so a re-dispatched beat resumes
   instead of restarting. Every employee gets it, and the factory must map it to a real dream builtin;
   Dream's generic standing orders direct its use.
2. **Skill materialization** — every employee declares a ``skills_root``, and the factory materializes
   it into a dream ``skill_registry`` (so its authored playbooks are loadable via the ``skill`` tool).

These are parametrized over the real default roles so a new employee (or a merge) can't silently drop
either wiring.
"""

from __future__ import annotations

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus_harness._factory import dream_tool_names

pytestmark = pytest.mark.integration

# The canonical craft employees whose multi-turn work uses durable checklists and skill bundles.
EMPLOYEES = [
    "analyst",
    "backend_engineer",
    "frontend_engineer",
    "designer",
    "marketer",
    "pm",
]


@pytest.fixture(scope="module")
def registry() -> RoleRegistry:
    return RoleRegistry.from_plugins(default_roles())


@pytest.mark.parametrize("role", EMPLOYEES)
def test_every_employee_gets_todo_write(registry: RoleRegistry, role: str) -> None:
    plugin = registry.get(role)
    assert plugin is not None, f"{role} is not registered"
    assert "todo_write" in plugin.manifest.tools, f"{role} is missing todo_write"


@pytest.mark.parametrize("role", EMPLOYEES)
def test_employee_briefs_leave_resume_guidance_to_dream(registry: RoleRegistry, role: str) -> None:
    # Dream's generic standing-orders prompt owns the shared resume/recall/tool-choice waist. Craft
    # briefs keep only role-specific judgment and must not duplicate those directives.
    brief = registry.get(role).manifest.system_prompt
    for marker in ("TOOL CHOICE", "RESUME, DON'T RESTART", "EPISODIC MEMORY"):
        assert marker not in brief, f"{role} brief duplicates shared standing order: {marker}"


def test_todo_write_maps_to_a_real_dream_builtin() -> None:
    # The chorus->dream map must keep todo_write (it was silently dropped once) so the harness enables it.
    assert dream_tool_names(("todo_write",)) == ("todo_write",)


@pytest.mark.parametrize("role", EMPLOYEES)
def test_every_employee_materializes_skills(registry: RoleRegistry, role: str) -> None:
    # A skills_root is what the factory materializes into a dream skill_registry — without it the
    # employee's authored playbooks are unreachable via the `skill` tool.
    manifest = registry.get(role).manifest
    assert manifest.skills_root is not None, f"{role} has no skills_root (skills won't materialize)"
    assert len(manifest.skills) >= 1, f"{role} declares no skills"
    assert "skill" in manifest.tools, f"{role} lacks the `skill` tool to load its playbooks"
