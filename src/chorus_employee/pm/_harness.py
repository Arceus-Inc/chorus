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
from chorus_employee.pm._subagents import RESEARCHER_SUBAGENT
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR


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
            # spawn_subagent — dispatch the Tier-1 Researcher mid-beat (§06). The web tools above are
            # also what the Researcher is capability-minimised from (it delegates them to web_research).
            "spawn_subagent",
        ),
        # — build_harness(subagents=…) — the Tier-1 specialists Piper may dispatch mid-beat (§06).
        # The Researcher gathers cited evidence (depth-2 over the shared web_research orchestrator) and
        # hands back a typed ResearchBrief whose source URLs the PM cites — clearing its grounding floor.
        # web_research is also exposed top-level (as the Marketer does) so Piper can run a direct sweep
        # without the Researcher wrapper; it is the Researcher's depth-2 child either way.
        subagents=(RESEARCHER_SUBAGENT, WEB_RESEARCH_ORCHESTRATOR),
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — beat time budget (depth-2 research reach) —
        # Piper can now spawn the Researcher, which itself nests web_research (depth-2) — a single beat
        # can hold a depth-2 live sweep, so widen the wall-clock to the Marketer's depth-2 budget or the
        # reaper claims it mid-nest. The org defaults (90s beat / 300s lease) are far too tight.
        beat_timeout_s=900.0,
        lease_ttl_s=1200.0,
        # — turn / sprint budget —
        # Read context, spawn the Researcher (one blocking turn), read its brief, write the plan: 15
        # turns leaves headroom for a spawn + a revision; 3 sprints lets a thin first pass gather more
        # evidence and converge on the grounded decision.
        max_turns=15,
        max_sprints=3,
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # REPO_WRITE_NET: writes its plan within its worktree AND may reach the net through the
        # *allowlist* — only hosts a registered tool declares (web_search/web_extract → api.tavily.com).
        # It runs no commands; research reach is read-only egress, not an open network.
        sandbox=SandboxTier.REPO_WRITE_NET,
    )


__all__ = ["pm_manifest"]
