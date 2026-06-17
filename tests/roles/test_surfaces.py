"""Role-surface overlays activate optional Dream harness capabilities."""

from __future__ import annotations

import pytest

from chorus.roles import RoleSurfaceOverride, apply_role_surface_overrides, default_roles

pytestmark = pytest.mark.unit


def _engineer():
    return next(plugin for plugin in default_roles() if plugin.name == "engineer")


def test_skills_override_enables_discovery_and_skill_tool() -> None:
    (engineer,) = [
        plugin
        for plugin in apply_role_surface_overrides(
            default_roles(), RoleSurfaceOverride(role="engineer", skills=True)
        )
        if plugin.name == "engineer"
    ]

    assert engineer.manifest.skills == ("project",)
    assert "skill" in engineer.manifest.tools


def test_mcp_and_plugins_override_only_selected_role() -> None:
    roles = apply_role_surface_overrides(
        default_roles(), RoleSurfaceOverride(role="engineer", mcp=True, plugins=True)
    )
    engineer = next(plugin for plugin in roles if plugin.name == "engineer")
    reviewer = next(plugin for plugin in roles if plugin.name == "reviewer")

    assert engineer.manifest.mcp is True
    assert engineer.manifest.plugins is True
    assert reviewer.manifest.mcp is False
    assert reviewer.manifest.plugins is False


def test_false_skills_override_removes_skill_tool() -> None:
    enabled = apply_role_surface_overrides(
        (_engineer(),), RoleSurfaceOverride(role="engineer", skills=True)
    )
    disabled = apply_role_surface_overrides(
        enabled, RoleSurfaceOverride(role="engineer", skills=False)
    )[0]

    assert disabled.manifest.skills == ()
    assert "skill" not in disabled.manifest.tools