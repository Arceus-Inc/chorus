"""RoleBeatConfig — the dream-free, beat-ready projection of a role (spec 06 §2, spec 05).

A role's :class:`RoleManifest` is the full standing contract; a *beat* needs only a slice of it: the
system prompt, the tool allow-list, the permission posture, and the memory scope. :func:`role_beat_config`
projects the manifest into that slice as plain strings — no dream import — so any front end (the public
``Chorus`` API, the CLI ``chat``) can resolve an employee's role to a beat config agnostically. The
composition root materializes this into a configured dream harness (the chorus→dream tool-name
mapping + the per-role overlays live there, at the seam). Tool names stay *chorus* names here.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus.roles._manifest import McpServerSpec, RoleManifest
from chorus.roles._subagent import SubagentSpec


@dataclass(frozen=True)
class RoleBeatConfig:
    """An employee's dream-harness identity — everything a beat needs to *be* that employee.

    The dream-free projection of the role's :class:`RoleManifest`, carrying **every** ``build_harness``
    knob: the system prompt (brief), the tool and skill allow-lists, the permission posture, the memory
    scope, and the engine scalars (``model``/``max_turns``/``working_memory``/``wake_model``/``mcp``/
    ``plugins``/``env``). The composition root materializes it into a configured dream harness —
    ``tools``/``skills``/``memory_scope``/the scalars at ``build_harness`` level,
    ``system_prompt``/``permission_mode`` written as per-role overlays — and the whole ``run_task``
    planner→generator→evaluator loop runs as that employee. ``permission_mode`` is already the
    dream-wire string (the chorus enum is a subset of dream's by value); ``tools``/``skills`` are chorus
    names. Frozen so it is hashable + safe to share across async beats.
    """

    system_prompt: str
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    permission_mode: str = "default"
    memory_scope: str = "project"
    isolation: str = "worktree"
    sandbox: str = "repo-write"
    model: str | None = None
    max_turns: int = 8
    max_sprints: int = 1  # per-beat sprint budget (spec 05): 1 = one beat is one sprint
    working_memory: bool = False
    wake_model: str | None = None
    mcp: bool = False
    plugins: bool = False
    # The MCP servers this role admits (→ ``.harness/mcp-allowlist.toml`` when ``mcp`` is True).
    mcp_servers: tuple[McpServerSpec, ...] = ()
    env: tuple[tuple[str, str], ...] = ()
    # Per-role beat time budget (``None`` → composition-root default). ``beat_timeout_s`` bounds the
    # DreamBeatRunner's wall-clock; ``lease_ttl_s`` the scheduler's run lease before the reaper claims.
    beat_timeout_s: float | None = None
    lease_ttl_s: float | None = None
    # Tier-1 role-owned subagents (carried through verbatim; the composition root projects them
    # onto dream's ``Subagent``/``SubagentSet`` and intersects each one's tools with this config's.
    subagents: tuple[SubagentSpec, ...] = ()
    # Filesystem dir of this role's ``<slug>/SKILL.md`` playbooks (None = no role skills).
    skills_root: str | None = None


def role_beat_config(manifest: RoleManifest) -> RoleBeatConfig:
    """Project a chorus :class:`RoleManifest` into the beat-ready :class:`RoleBeatConfig`."""
    return RoleBeatConfig(
        system_prompt=manifest.system_prompt,
        tools=manifest.tools,
        skills=manifest.skills,
        permission_mode=manifest.permission_mode.value,
        memory_scope=manifest.memory_scope.value,
        isolation=manifest.isolation.value,
        sandbox=manifest.sandbox.value,
        model=manifest.model,
        max_turns=manifest.max_turns,
        max_sprints=manifest.max_sprints,
        working_memory=manifest.working_memory,
        wake_model=manifest.wake_model,
        mcp=manifest.mcp,
        plugins=manifest.plugins,
        mcp_servers=manifest.mcp_servers,
        env=manifest.env,
        beat_timeout_s=manifest.beat_timeout_s,
        lease_ttl_s=manifest.lease_ttl_s,
        subagents=manifest.subagents,
        skills_root=manifest.skills_root,
    )


__all__ = ["RoleBeatConfig", "role_beat_config"]
