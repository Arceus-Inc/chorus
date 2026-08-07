"""``with_web_research`` — splice the Web-Research Orchestrator into any role that wants it.

chorus projects only **Tier-1** (role-owned) subagents today, so a "shared" subagent is realized
by defining it once (:data:`WEB_RESEARCH_ORCHESTRATOR`) and adding it to each opted-in role's
manifest. This helper also grants the parent the orchestrator's tools (``browser_run`` /
``web_fetch``) — because narrower-wins intersects a subagent's tools with its parent's.

The grant is monotone: it only ever *widens* the manifest (adds tools, appends the subagent, and
raises the sandbox to at least ``REPO_WRITE_NET`` for Chromium CDP egress). A role already at
``UNRESTRICTED`` keeps it; an already-present subagent is not duplicated.
"""

from __future__ import annotations

from dataclasses import replace

from chorus.roles._manifest import RoleManifest, SandboxTier
from swarm.web_research_orchestrator._subagent import (
    WEB_RESEARCH_ORCHESTRATOR,
    WEB_RESEARCH_SUBAGENT_TOOLS,
)

WEB_RESEARCH_TOOLS: tuple[str, ...] = ("spawn_subagent", *WEB_RESEARCH_SUBAGENT_TOOLS)


def _raise_to_net(current: SandboxTier) -> SandboxTier:
    """Raise the sandbox to at least ``REPO_WRITE_NET`` without ever lowering it."""
    if current in (SandboxTier.REPO_WRITE_NET, SandboxTier.UNRESTRICTED):
        return current
    return SandboxTier.REPO_WRITE_NET


def with_web_research(manifest: RoleManifest) -> RoleManifest:
    """Return ``manifest`` widened to spawn the Web-Research Orchestrator."""
    tools = tuple(dict.fromkeys((*manifest.tools, *WEB_RESEARCH_TOOLS)))
    subagents = manifest.subagents
    if all(s.name != WEB_RESEARCH_ORCHESTRATOR.name for s in subagents):
        subagents = (*subagents, WEB_RESEARCH_ORCHESTRATOR)
    return replace(
        manifest,
        tools=tools,
        subagents=subagents,
        sandbox=_raise_to_net(manifest.sandbox),
    )


__all__ = ["WEB_RESEARCH_TOOLS", "with_web_research"]
