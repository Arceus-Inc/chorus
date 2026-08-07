"""The CEO's dream-harness manifest — every ``build_harness`` component, in one place.

A CEO **reads the company's state, weighs evidence, and writes a directive**: it reads broadly to
ground the call, may pull external context, keeps working notes across steps, and writes the directive
that is its deliverable. Its authority is deliberately narrow — it reads the world but writes *only* its
own worktree: no ``git`` (it never commits/pushes; the lander snapshots), no system-of-record writes,
no send/spend. The CEO's power is judgement, not privilege — its directive is a recommendation the org
acts on through the normal gates, not a unilateral write. Each field below names the dream component it
drives.
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
from chorus_employee.ceo._brief import CEO_BRIEF
from chorus_employee.ceo._subagents import CEO_SUBAGENTS

_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def ceo_manifest() -> RoleManifest:
    """The complete harness identity of a CEO (spec 06 §2 -> dream ``build_harness``)."""
    return RoleManifest(
        # - per-role overlay -
        system_prompt=CEO_BRIEF,
        # ACCEPT_EDITS: the CEO writes its directive autonomously — there is no human to approve the
        # edit, so file writes auto-apply, bounded by the sandbox below. It writes only its worktree.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # - build_harness(registry=...) -
        # read the state, optionally gather external context, persist the directive, keep working notes.
        # Deliberately NO ``git`` and no data/spend tools — the CEO governs, it does not crunch or pay;
        # the lander commits the directive, not the model. NO ``repo_search`` either: the CEO's source of
        # truth about the company is ``governance_read`` (the live direction), not code grep — and in a
        # governance beat repo_search only dead-ends on the near-empty worktree, burning turns. The
        # governance_* tools are the CEO's authority: they bind (at the composition root) to horizon's
        # direction via a dream ``GovernancePort`` — the employee reads the tree and steers it
        # (approve/reject proposals, reprioritise/archive goals), exactly as the manager's ``submit_task``
        # binds to the ledger. Dropped fail-closed if no port.
        tools=(
            "read_file",
            "write_file",
            "run_command",
            "browser_run",
            "web_fetch",
            "read_offloaded",
            "skill",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "governance_read",
            "roadmap_propose",
            "proposal_approve",
            "proposal_reject",
            "goal_set_priority",
            "goal_archive",
            "workforce_catalog_read",
            "workforce_plan_propose",
        ),
        # - build_harness(memory=...) + working_memory -
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # an in-task scratchpad to carry the review across turns
        # - build_harness(max_turns=...) -
        # a governance review is multi-step (read the tree -> read goals/proposals -> weigh -> decide ->
        # write), and a thorough audit legitimately needs headroom to inspect several issues.
        max_turns=18,
        # - per-beat sprint budget (spec 05) -
        max_sprints=3,
        # - worktree containment (spec 04 §4) -
        isolation=Isolation.WORKTREE,
        # - trust posture (spec 04 §4) -> .harness/sandbox.toml -
        # unrestricted *within the isolated worktree*: the CEO may run light commands to sanity-check
        # numbers, which dream otherwise gates behind an approval the kernel can't supply. dream's
        # credential guard, command-deny list, and worktree confinement still apply, and the toolset
        # carries no ``git`` — so "read the world, write only my worktree" holds.
        sandbox=SandboxTier.UNRESTRICTED,
        # - build_harness(subagents=...) - Tier-1 specialists the CEO may dispatch mid-beat. Each
        # subagent's tools are a subset of the CEO's toolset (intersected at materialize).
        subagents=CEO_SUBAGENTS,
        # - build_harness(skill_registry=...) - the CEO's authored playbooks, discovered from this
        # package's ``skills/`` dir and offered via the `skill` tool: the executive operating procedures
        # the brief promotes — decision-making, prioritization, capital allocation, governance, risk,
        # metrics, and communication.
        skills=(
            "executive-decision-making",
            "strategic-prioritization",
            "how-to-plan-a-roadmap",
            "capital-allocation",
            "governance-and-oversight",
            "risk-and-downside-management",
            "okrs-and-metrics",
            "stakeholder-communication",
        ),
        skills_root=_SKILLS_ROOT,
        # — beat time budget — multi-step governance review (P0 #6) —
        beat_timeout_s=900.0,
        lease_ttl_s=1200.0,
    )


__all__ = ["ceo_manifest"]
