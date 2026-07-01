"""The Marketer's dream-harness manifest — every ``build_harness`` component, in one place.

A Marketer **reads the funnel and market, drafts content/creatives, and stages campaigns for
go-live**. She needs file-read, file-write (to her worktree), web search (market research),
and memory surfaces — but no command execution and no ungated external writes. Each field below
names the dream component it drives.
"""

from __future__ import annotations

from pathlib import Path

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.marketer._brief import MARKETER_BRIEF
from chorus_employee.marketer._subagents import BRAND_CRITIC_SUBAGENT, CREATIVE_SUBAGENT
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR

# Authored playbooks discovered from this package's ``skills/`` dir and offered via the ``skill`` tool.
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


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
            # market/audience research: Tavily-backed web search (§06 Researcher, §07 read reach).
            # An allowlisted-egress read (its declared host is api.tavily.com) — needs the net tier below.
            "web_search",
            # web_extract (fetch + clean read) — the second tool the Web-Research Orchestrator needs;
            # granted directly so narrower-wins doesn't strip it from that subagent at materialize.
            "web_extract",
            # the ONLY path to a live surface: stage publish/send/spend for human approval (§07/§11).
            # Its call opens a gate and never executes — reach is fail-closed by construction.
            "stage_go_live",
            # deterministic pre-gen self-check (§08 tool / §10 sandwich): mechanically scan her draft for
            # prohibited phrases + unsubstantiated claims before she spawns the (expensive) Brand-Critic.
            "brand_lint",
            # the Channel's reversible write (§08 cms.draft): stage finished content as an UNPUBLISHED
            # CMS draft (blog/social/email). Below the go-live gate — publishing it is still stage_go_live.
            "cms_draft",
            # the `skill` tool loads her authored playbooks (brand-voice) on demand (§08 know-how).
            "skill",
        ),
        disallowed_tools=(),
        # --- build_harness(skills=...) / build_harness(skill_registry=...) ---
        # The brand-voice playbook (§08): authored craft that keeps a fluent model from being an
        # on-message-sounding, off-brand fabricator — the deterministic-rules complement to the
        # in-beat Brand-Critic. Discovered from the package's skills/ dir; loaded via the skill tool.
        skills=("brand-voice",),
        skills_root=_SKILLS_ROOT,
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
        # --- beat time budget (research-heavy) ---
        # Mira spawns the Web-Research Orchestrator, a multi-minute web_search/web_extract sweep that
        # blocks the beat in one uninterrupted call. The org defaults (90s beat / 300s lease) reap her
        # mid-research; widen both so a research beat (spawn → draft → brand_critic) runs to done.
        beat_timeout_s=480.0,
        lease_ttl_s=900.0,
        # --- worktree containment ---
        isolation=Isolation.WORKTREE,
        # --- trust posture ---
        # REPO_WRITE_NET: writes drafts within her worktree AND may reach the net through the
        # *allowlist* — only hosts a registered tool declares (web_search → api.tavily.com). She runs
        # no commands, and her only outbound-write surface (publish/send/spend) is still the gated
        # stage_go_live tool. Research reach is read-only egress, not an open network.
        sandbox=SandboxTier.REPO_WRITE_NET,
        # --- subagents (Tier-1, role-owned) ---
        # The Brand-Critic: an adversarial reviewer Mira spawns mid-beat to validate content
        # against the voice spec. Read-only (can only inspect, never edit the draft).
        # The Web-Research Orchestrator: a shared specialist (declared once in src/swarm/) she spawns to
        # answer a market/audience question from the live web (web_search + web_extract), returning a
        # runtime-validated WebResearchOutput. Passed directly — no with_web_research indirection.
        # The Creative/Copywriter: a variation engine she spawns on a grounded seed to draft a set of
        # on-brand variants (§10 variety). Writes to her worktree (candidates/), never publishes or
        # selects; returns a typed CreativeManifest. It self-lints via brand_lint.
        subagents=(BRAND_CRITIC_SUBAGENT, CREATIVE_SUBAGENT, WEB_RESEARCH_ORCHESTRATOR),
    )


__all__ = ["marketer_manifest"]
