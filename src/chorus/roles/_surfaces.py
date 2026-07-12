"""Role-surface overlays for opt-in harness capabilities (spec 06 §2).

These helpers are SDK-level: front ends can activate role surfaces such as project skill discovery,
MCP, and repo-local plugins without mutating the base role definitions or special-casing the CLI.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace

from chorus.roles._plugin import RolePlugin

_PROJECT_SKILL_DISCOVERY = ("project",)
_SKILL_TOOL = "skill"


@dataclass(frozen=True)
class RoleSurfaceOverride:
    """Optional surface toggles for one role manifest."""

    role: str
    skills: bool | None = None
    mcp: bool | None = None
    plugins: bool | None = None


def apply_role_surface_overrides(
    plugins: Iterable[RolePlugin], *overrides: RoleSurfaceOverride
) -> tuple[RolePlugin, ...]:
    """Return role plugins with selected manifest surface flags overlaid.

    ``skills=True`` enables Dream's project/user/bundled skill discovery by making the manifest's
    skill tuple non-empty when it was previously empty; Chorus still lets Dream own discovery.
    """
    by_role = {override.role: override for override in overrides}
    out: list[RolePlugin] = []
    for plugin in plugins:
        override = by_role.get(plugin.name)
        if override is None:
            out.append(plugin)
            continue
        manifest = plugin.manifest
        skills = manifest.skills
        if override.skills is True and not skills:
            skills = _PROJECT_SKILL_DISCOVERY
        elif override.skills is False:
            skills = ()
        tools = manifest.tools
        if override.skills is True and _SKILL_TOOL not in tools:
            tools = (*tools, _SKILL_TOOL)
        elif override.skills is False:
            tools = tuple(tool for tool in tools if tool != _SKILL_TOOL)
        out.append(
            replace(
                plugin,
                manifest=replace(
                    manifest,
                    tools=tools,
                    skills=skills,
                    mcp=manifest.mcp if override.mcp is None else override.mcp,
                    plugins=manifest.plugins if override.plugins is None else override.plugins,
                ),
            )
        )
    return tuple(out)


__all__ = ["RoleSurfaceOverride", "apply_role_surface_overrides"]
