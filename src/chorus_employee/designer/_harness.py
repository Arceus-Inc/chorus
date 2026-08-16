"""The Designer's dream-harness manifest — every ``build_harness`` component, in one place (designer §02/§08).

A Designer **reads the design system, the codebase, and prior art; explores on-system variants; self-lints
for tokens + accessibility; and writes a design spec to its worktree**. It needs file-read, file-write
(to its worktree), web search (pattern research), memory surfaces, and the ``design_lint`` primitive — but
**no command execution and no git**: it reads the system and code, writes its design, and its only
outbound-write surface (a handoff that ships UI) is a gated tool added in a later slice. Each field below
names the dream component it drives.
"""

from __future__ import annotations

from pathlib import Path

from chorus.roles._manifest import (
    DREAM_DEFAULT_MAX_SPRINTS,
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.designer._brief import DESIGNER_BRIEF
from chorus_employee.designer._subagents import DESIGN_CRITIC_SUBAGENT
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR

# Authored playbooks discovered from this package's ``skills/`` dir and offered via the ``skill`` tool.
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def designer_manifest() -> RoleManifest:
    """The complete harness identity of a Designer (designer §02 -> dream ``build_harness``)."""
    return RoleManifest(
        # --- per-role overlay ---
        system_prompt=DESIGNER_BRIEF,
        # ACCEPT_EDITS: the Designer writes its spec + variants to its worktree autonomously.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # --- build_harness(registry=...) ---
        # Read-broad + design-write: read DESIGN.md/code/prior-art, write the spec, self-lint.
        # No run_command (it doesn't build/test), no git (it doesn't ship PRs) — designer §08/§12.
        tools=(
            "read_file",
            "write_file",
            "todo_write",  # durable cross-beat checklist (TODO.md) — resume, don't restart
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            # read your own past episodic beats — recency/keyword, outcome attached
            # (spec 07 §11). The reasoning-recall counterpart to memory_search's durable facts.
            "recall",
            "lattice_context",
            "lattice_packet",
            "lattice_apply",
            "skill_manage",
            "spawn_subagent",
            # pattern/prior-art research via Chromium CDP (designer §06 web_research,
            # §07 pattern research). Needs the net tier below.
            "browser_run",
            "web_fetch",
            # the load-bearing primitive: the deterministic a11y/token scan the Critic grounds its
            # verdict on (designer §08/§10 — the exact analog of the Marketer's brand_lint).
            "design_lint",
            # read-only exemplar fetcher: pulls a vendored real-world DESIGN.md (Stripe/Linear/…) from
            # the design-md-exemplars library — which lives in the chorus package, NOT the worktree, so
            # a worktree-confined read_file can't reach it. This is how the exemplars become readable.
            "design_exemplar",
            # the `skill` tool loads the authored design-craft playbooks on demand (designer §08).
            "skill",
        ),
        disallowed_tools=(),
        # --- build_harness(skills=...) / build_harness(skill_registry=...) ---
        # Authored §08 design-craft playbooks — durable know-how (accessibility, tokens, layout,
        # interaction, flow, handoff), loaded on demand via the `skill` tool, discovered from skills/.
        skills=(
            "design-system-authoring",
            "design-md-exemplars",
            "token-scale-discipline",
            "component-api-design",
            "wcag-conformance",
            "keyboard-and-focus",
            "color-contrast",
            "visual-hierarchy",
            "responsive-layout",
            "information-density",
            "interaction-patterns",
            "states-empty-loading-error",
            "motion-restraint",
            "user-flow-mapping",
            "microcopy-in-ui",
            "design-critique-method",
            "design-spec-writing",
        ),
        skills_root=_SKILLS_ROOT,
        # --- build_harness(memory=...) + working_memory ---
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # tracks explored states / pruned variants across a multi-screen flow
        # --- build_harness(model=...) ---
        model=None,  # use the deployment model the composition root supplies
        wake_model=None,
        # --- build_harness(max_turns=...) ---
        # The frame→lint→critic→revise loop is turn-hungry: read system, draft, self-lint, spawn
        # critic, revise, re-spawn. 20 turns leaves room for ~3 critic rounds without starving the beat.
        max_turns=20,
        # --- per-beat sprint budget ---
        # On-system convergence takes a few passes (the Design-Critic is deliberately strict), so a
        # design beat needs more sprints than a code beat. 5 lets a rough first draft cool to on-system.
        max_sprints=DREAM_DEFAULT_MAX_SPRINTS,
        # --- build_harness(mcp=...) / build_harness(plugins=...) ---
        mcp=False,  # the live Figma MCP connect layer (designer §07) is a follow-up slice
        plugins=False,
        # --- build_harness(env=...) ---
        env=(),
        # --- beat time budget (research-heavy) ---
        # A single beat can hold a live pattern-research sweep plus an explore fan-out, so widen the
        # wall-clock past the code-role defaults or the reaper claims the beat mid-research.
        beat_timeout_s=900.0,
        lease_ttl_s=1200.0,
        # --- worktree containment ---
        isolation=Isolation.WORKTREE,
        # --- trust posture ---
        # REPO_WRITE_NET: writes its spec within its worktree AND may reach the net through the
        # *allowlist* — browser_run talks to Chromium CDP (DREAM_CHROMIUM_CDP_URL). It runs no
        # commands; its only outbound-write surface (handoff/ship) is a gated tool added later. Pattern
        # research is read-only egress, not an open network.
        sandbox=SandboxTier.REPO_WRITE_NET,
        # Lean roster: design_critic (adversarial PASS/FAIL) + web_research.
        # UX framing / layout exploration → skills on the main employee.
        subagents=(DESIGN_CRITIC_SUBAGENT, WEB_RESEARCH_ORCHESTRATOR),
    )


__all__ = ["designer_manifest"]
