"""The Marketer's dream-harness manifest — every ``build_harness`` component, in one place.

A Marketer **reads the funnel and market, drafts content/creatives, and stages campaigns for
go-live**. She needs file-read, file-write (to her worktree), web search (market research),
and memory surfaces — but no command execution and no ungated external writes. Each field below
names the dream component it drives.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.marketer._brief import MARKETER_BRIEF
from chorus_employee.marketer._subagents import BRAND_CRITIC_SUBAGENT


def marketer_manifest() -> RoleManifest:
    """The complete harness identity of a Marketer (design doc §02 -> dream ``build_harness``)."""
    return RoleManifest(
        # --- per-role overlay ---
        system_prompt=MARKETER_BRIEF,
        # ACCEPT_EDITS: the Marketer writes drafts to her worktree autonomously (content, creatives).
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # --- build_harness(registry=...) ---
        # Read-heavy + draft-write: market research, analytics read, content drafting.
        # No run_command (she doesn't build/test), no git (she doesn't ship PRs).
        tools=(
            "read_file",
            "write_file",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            "spawn_subagent",
            # the ONLY path to a live surface: stage publish/send/spend for human approval (§07/§11).
            # Its call opens a gate and never executes — reach is fail-closed by construction.
            "stage_go_live",
        ),
        disallowed_tools=(),
        # --- build_harness(skills=...) ---
        skills=(),  # brand-voice, experiment-design skills are a follow-up
        # --- build_harness(memory=...) + working_memory ---
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # tracks campaign state, creative variants across turns
        # --- build_harness(model=...) ---
        model=None,  # use the deployment model the composition root supplies
        wake_model=None,
        # --- build_harness(max_turns=...) ---
        # The draft→critic→revise loop is turn-hungry: read spec, draft, spawn critic, revise, re-spawn.
        # 20 turns leaves room for ~3 critic rounds without starving the beat mid-revision.
        max_turns=20,
        # --- per-beat sprint budget ---
        # Brand convergence takes a few passes (the Brand-Critic is deliberately strict), so a content
        # beat needs more sprints than a code beat. 5 lets a hot first draft cool to on-brand.
        max_sprints=5,
        # --- build_harness(mcp=...) / build_harness(plugins=...) ---
        mcp=False,  # MCP integrations (analytics, ad platforms) are a follow-up
        plugins=False,
        # --- build_harness(env=...) ---
        env=(),
        # --- worktree containment ---
        isolation=Isolation.WORKTREE,
        # --- trust posture ---
        # REPO_WRITE: may write files (drafts) within her isolated worktree, but runs no commands
        # and has no network. Gated write surfaces (publish/send/spend) are a follow-up via
        # WebPlugin trust layer.
        sandbox=SandboxTier.REPO_WRITE,
        # --- subagents (Tier-1, role-owned) ---
        # The Brand-Critic: an adversarial reviewer Mira spawns mid-beat to validate content
        # against the voice spec. Read-only (can only inspect, never edit the draft).
        subagents=(BRAND_CRITIC_SUBAGENT,),
    )


__all__ = ["marketer_manifest"]
