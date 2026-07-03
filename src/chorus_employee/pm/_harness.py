"""The PM's dream-harness manifest — every ``build_harness`` component, in one place.

A PM **reads context, researches evidence, and writes a plan doc**: it needs the file-read and
file-write surfaces, a worktree it can write into, and Tavily-backed web reach to gather the cited
evidence its grounding floor (``_dod``) demands — but no command execution and no open network. Each
field below names the dream component it drives.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.pm._brief import PM_BRIEF


def pm_manifest() -> RoleManifest:
    """The complete harness identity of a PM (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=PM_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        # ACCEPT_EDITS: the PM writes its plan doc autonomously — there is no human to approve the edit,
        # so file writes auto-apply (as the Engineer does), bounded by the repo-write sandbox below.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # — build_harness(registry=…) —
        # Read to gather context, research to ground the decision, write to persist the plan. The web
        # tools are the §08 shelf that lets the PM satisfy its own grounding floor (a cited source),
        # rather than only echoing evidence handed to it (§07 read reach, §10 confidence policy).
        # No run_command (it doesn't build/test) and no git (it doesn't ship PRs).
        tools=(
            "read_file",
            "write_file",
            # Tavily-backed web search — an allowlisted-egress read (host: api.tavily.com); needs the
            # net sandbox tier below. This is the PM's read reach onto the live web (§07/§08).
            "web_search",
            # web_extract (fetch + clean read) — read a candidate source in full to ground a claim,
            # not just cite a search snippet. Same allowlisted host as web_search.
            "web_extract",
        ),
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — beat time budget (research reach) —
        # A live web sweep blocks the beat in one uninterrupted call; the org defaults (90s beat /
        # 300s lease) would reap the PM mid-research, so widen both. Inline (no depth-2 nesting yet),
        # so lighter than the Marketer's 900/1200.
        beat_timeout_s=300.0,
        lease_ttl_s=600.0,
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # REPO_WRITE_NET: writes its plan within its worktree AND may reach the net through the
        # *allowlist* — only hosts a registered tool declares (web_search/web_extract → api.tavily.com).
        # It runs no commands; research reach is read-only egress, not an open network.
        sandbox=SandboxTier.REPO_WRITE_NET,
    )


__all__ = ["pm_manifest"]
