"""The Analyst's dream-harness manifest — every ``build_harness`` component, in one place.

An Analyst **reads context, runs analysis code, and writes a findings doc**: it reads to gather
evidence, runs computation in its own worktree to ground conclusions, keeps working notes across
steps, and writes the findings file that is its deliverable. Its authority is deliberately narrow —
it reads broadly but writes *only* its own worktree: no ``git`` (it never commits/pushes; the lander
snapshots), no system-of-record writes, no send/spend. Each field below names the dream component it
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
from chorus_employee.analyst._brief import ANALYST_BRIEF
from chorus_employee.analyst._subagents import ANALYST_SUBAGENTS

_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def analyst_manifest() -> RoleManifest:
    """The complete harness identity of an Analyst (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=ANALYST_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        # ACCEPT_EDITS: the Analyst writes its findings doc autonomously — there is no human to approve
        # the edit, so file writes auto-apply (as the Engineer does), bounded by the sandbox below.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # — build_harness(registry=…) —
        # read evidence, run analysis code, persist findings, and keep working notes. Deliberately NO
        # ``git`` — the Analyst writes only its worktree; the lander commits the finding, not the model.
        # The analysis tools (warehouse_query / repo_search / notebook_run / chart_render) are chorus
        # dream-BaseTools registered by the composition root when listed here.
        tools=(
            "read_file",
            "write_file",
            "todo_write",  # durable cross-beat checklist (TODO.md) — resume, don't restart
            "run_command",
            "repo_search",
            "warehouse_query",
            "web_search",
            "web_extract",
            "read_offloaded",
            "notebook_run",
            "chart_render",
            "skill",
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            # read your own past episodic beats — recency/keyword, outcome attached
            # (spec 07 §11). The reasoning-recall counterpart to memory_search's durable facts.
            "recall",
            "lattice_context",
            "lattice_packet",
            "lattice_apply",
        ),
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # an in-task scratchpad to carry analysis state across turns
        # — build_harness(max_turns=…) —
        # analysis is multi-step (read → script → run → read output → conclude), and a real
        # investigation may need a couple of script fixes within one sprint; give it headroom. Deep
        # distinguished-engineer tasks (capacity models, sensitivity analysis) legitimately need more
        # steps to derive, compute, and write, so keep the ceiling generous.
        max_turns=20,
        # — per-beat sprint budget (spec 05) —
        # a real investigation rarely lands in one sprint; widen so one Analyst beat runs to a finding
        # instead of stopping after the first sprint with `needs-changes` and waiting on re-dispatch.
        max_sprints=4,
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # unrestricted *within the isolated worktree*: the Analyst must run analysis commands (python,
        # etc.), which dream otherwise gates behind an interactive approval the kernel can't supply.
        # dream's credential guard, command-deny list, and worktree confinement still apply, and the
        # toolset carries no ``git`` — so "read the world, write only my worktree" holds.
        sandbox=SandboxTier.UNRESTRICTED,
        # — build_harness(subagents=…) — Tier-1 specialists the Analyst may dispatch mid-beat. Each
        # subagent's tools are a subset of the Analyst's toolset (intersected at materialize).
        subagents=ANALYST_SUBAGENTS,
        # — build_harness(skill_registry=…) — the Analyst's authored playbooks, discovered from this
        # package's ``skills/`` dir and offered via the `skill` tool. A distinguished-analyst library:
        # the investigation spine plus rigor, causal, modeling, research, experiment, tradeoff, and
        # communication methods — the standing operating procedure the brief promotes.
        skills=(
            "analytics-diagnostic-method",
            "exploratory-data-analysis",
            "sql-investigation",
            "trend-and-correlation",
            "statistical-rigor",
            "causal-inference",
            "predictive-modeling",
            "web-research",
            "experiment-analysis",
            "metric-definition-and-benchmarks",
            "technical-tradeoff-analysis",
            "findings-communication",
        ),
        skills_root=_SKILLS_ROOT,
    )


__all__ = ["analyst_manifest"]
