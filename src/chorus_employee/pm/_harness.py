"""The PM's dream-harness manifest — every ``build_harness`` component, in one place.

A PM **reads context, researches evidence, and writes a plan doc**: it needs the file-read and
file-write surfaces, a worktree it can write into, and Tavily-backed web reach to gather the cited
evidence its grounding floor (``_dod``) demands — but no command execution and no open network. Each
field below names the dream component it drives.
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
from chorus_employee.pm._brief import PM_BRIEF
from chorus_employee.pm._subagents import CRITIC_SUBAGENT, RESEARCHER_SUBAGENT
from swarm.web_research_orchestrator import WEB_RESEARCH_ORCHESTRATOR

# The PM's authored playbooks live beside this package; the `skill` tool loads a body on demand (§08).
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


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
            # Product-state read (§03 input ①) — the internal half of the evidence, beside the web:
            # repo_search reads the codebase (what's shipped / feasibility) and warehouse_query reads
            # usage/funnel metrics (is this the real gap?). Both tier-0 read-only, so they clear the
            # REPO_WRITE_NET sandbox — no command execution, no writes.
            "repo_search",
            "warehouse_query",
            # spawn_subagent — dispatch the Tier-1 Researcher mid-beat (§06). The web tools above are
            # also what the Researcher is capability-minimised from (it delegates them to web_research).
            "spawn_subagent",
            # record_decision — the §10 Decision OS write: record the decision as an immutable, cited
            # ledger object (confidence-floor-gated, mirrors decision.json). The PM's only ledger write.
            "record_decision",
            # skill — load an authored playbook on demand (§08). The PM's competence is its skill library,
            # not more verbs; this is the load-bearing tool for how it frames, decides, and writes.
            "skill",
            # read_offloaded — pairs with `skill`: a large playbook body (or any large tool result) is
            # truncated inline and offloaded to scratch with a "Full output saved to: <file>" pointer.
            # Without this the PM only ever sees the first ~800 chars of a big SKILL.md; with it, it pulls
            # the full playbook (and any bundled file it read) back into context. Tier-0, scratch-confined.
            "read_offloaded",
        ),
        # — build_harness(subagents=…) — the Tier-1 specialists Piper may dispatch mid-beat (§06).
        # The Researcher gathers cited evidence (depth-2 over the shared web_research orchestrator) and
        # hands back a typed ResearchBrief whose source URLs the PM cites — clearing its grounding floor.
        # web_research is also exposed top-level (as the Marketer does) so Piper can run a direct sweep
        # without the Researcher wrapper; it is the Researcher's depth-2 child either way.
        # The Critic (read-only, adversarial) red-teams the drafted decision BEFORE record_decision —
        # the qualitative pre-record check the deterministic grounding floor cannot make (the Marketer's
        # Brand-Critic analog); it returns a typed DecisionCritique (PASS/REVISE + findings).
        subagents=(RESEARCHER_SUBAGENT, WEB_RESEARCH_ORCHESTRATOR, CRITIC_SUBAGENT),
        # — build_harness(skill_registry=…) — the PM's authored playbooks, discovered from this package's
        # ``skills/`` dir and offered via the `skill` tool (§08). Slice 1 ships the Decision-core group —
        # the method behind the Decision OS (evidence -> options -> decision -> recommendation); later
        # slices add Discovery / Prioritization / Validation / Definition / Market / Business / etc.
        skills=(
            # The curated top-20 PM playbooks — highest-leverage across the value chain (§08),
            # ported from the Arceus PM library. The `skills` tuple documents the intended set;
            # the live catalogue is whatever materializes from `skills_root`.
            # Decision-core — the method behind the Decision OS (evidence → options → decision → rec).
            "evidence-brief",
            "options-set-generator",
            "decision-record",
            "recommendation-canvas",
            # Discovery & framing — frame the problem and uncover unmet needs before any solution.
            "problem-statement",
            "problem-framing-canvas",
            "jobs-to-be-done",
            "proto-persona",
            "discovery-process",
            # Prioritization & roadmap — what to build next, and in what order.
            "opportunity-solution-tree",
            "prioritization-advisor",
            "roadmap-planning",
            # Definition — turn a decision into buildable requirements.
            "prd-development",
            "user-story-mapping",
            # Validation — frame a bet as a testable hypothesis.
            "epic-hypothesis",
            "lean-ux-canvas",
            # Market & positioning — how the product is framed and the forces around it.
            "positioning-statement",
            "pestel-analysis",
            # Business & metrics — size the opportunity and read the growth signals.
            "tam-sam-som-calculator",
            "saas-revenue-growth-metrics",
        ),
        skills_root=_SKILLS_ROOT,
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — beat time budget (depth-2 research reach) —
        # Piper can now spawn the Researcher, which itself nests web_research (depth-2) — a single beat
        # can hold a depth-2 live sweep, so widen the wall-clock to the Marketer's depth-2 budget or the
        # reaper claims it mid-nest. The org defaults (90s beat / 300s lease) are far too tight.
        beat_timeout_s=900.0,
        lease_ttl_s=1200.0,
        # — turn / sprint budget —
        # The full loop is: gather evidence, draft the plan, red-team it with the Critic ONCE, apply the
        # verdict, then record + finalize. A tight budget is deliberate (a wide one lets the model fan
        # out the Researcher/Critic many times), but 2 sprints left no room to record AFTER the Critic's
        # revise — so 3 sprints: draft → critique → revise+record. The Critic is calibrated to PASS a
        # sound decision, so this does not reopen the fan-out loop.
        max_turns=12,
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
