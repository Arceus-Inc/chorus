"""The Backend Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

The Backend Engineer is the Engineer's structural twin (spec §02), so this manifest is a re-point of
the Engineer's: the same build-and-run toolset, the same ``UNRESTRICTED`` sandbox within an isolated
worktree (it must install packages and run arbitrary build/test commands), with a deeper turn budget
because the implement → run → test → fix loop is turn-hungry. It carries the ``test_evidence`` proof
primitive (§10) and the ``api_verifier`` subagent (§16 Slice 3 — an independent grader that boots the
built service and probes it over real HTTP); the net-allowlist refinement lands in a later slice.
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
from chorus_employee.backend_engineer._brief import BACKEND_ENGINEER_BRIEF
from chorus_employee.backend_engineer._subagents import (
    API_VERIFIER_SUBAGENT,
    CODE_REVIEWER_SUBAGENT,
    TEST_AUTHOR_SUBAGENT,
)

# Authored playbooks discovered from this package's ``skills/`` dir and offered via the ``skill`` tool.
_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def backend_engineer_manifest() -> RoleManifest:
    """The complete harness identity of a Backend Engineer (spec §16 Slice 1 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=BACKEND_ENGINEER_BRIEF,
        permission_mode=PermissionMode.ACCEPT_EDITS,  # writes code to its own worktree
        # — build_harness(registry=…) — the build-and-run toolset (+ Dream's memory surfaces) —
        tools=(
            "read_file",
            "write_file",
            "run_command",  # the workhorse: install, build, migrate, run, test
            "git",
            # the load-bearing proof primitive (§10): run the discovered verify commands + collate a
            # durable test_evidence/ bundle. "it was tested" becomes a file on disk, not a claim.
            "test_evidence",
            # the safety floor (§09): scan the worktree for hardcoded credentials + write a durable
            # security_scan/ report. "no secrets in the diff" becomes a file on disk, not a claim.
            "secret_scan",
            # the §09 Maintainable floor: a stack-blind executor for the format/lint/type checks the
            # engineer discovers via the verifying-any-stack skill → durable code_quality/ report.
            "code_quality",
            "skill",  # load the backend-craft playbooks on demand (verifying-any-stack, …)
            # durable cross-beat checklist (§04 progress+task list): todo_write atomically writes a
            # TODO.md into the worktree, so a beat that times out mid-build leaves a resume point the
            # next beat reads instead of restarting. The reconcile protocol lives in the brief.
            "todo_write",
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
            # dispatch the api_verifier subagent mid-beat (§16 Slice 3) — the grader that boots the
            # built service and probes it over real HTTP; its tools narrow this set at materialize.
            "spawn_subagent",
        ),
        disallowed_tools=(),
        # — build_harness(skills=…) / (skill_registry=…) — authored craft playbooks, loaded on demand
        # via the `skill` tool; discovered from this package's skills/ dir. The first is the
        # framework-agnostic quality-gate know-how behind the code_quality tool.
        skills=("structuring-any-service", "verifying-any-stack"),
        skills_root=_SKILLS_ROOT,
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # a scratchpad across the implement → run → fix turns
        # — build_harness(model=…) —
        model=None,  # the deployment model the composition root supplies
        wake_model=None,
        # — build_harness(max_turns=…) — implement → install → run → test → fix is turn-hungry —
        max_turns=18,
        # — per-beat sprint budget (spec 05): a build cools to green over a few passes in one beat —
        max_sprints=6,
        # — wall-clock per beat (DreamBeatRunner) — the heaviest beat of any role: it BUILDS a running
        # service, INSTALLS its real quality tools (ruff/mypy — no gaming), BOOTS it, RESTARTS it
        # (durability proof), and runs the full test sandwich (test_author + api_verifier + test_evidence),
        # each spending real wall-clock (installs, server polls, sleeps, subprocesses) on top of many
        # model turns. The 90s default is far too tight; a real multi-file service lands around 10-15 min.
        beat_timeout_s=900.0,
        # — run-lease TTL — must OUTLIVE the beat's own wall-clock budget so the stale-run reaper never
        # claims a beat that is still legitimately running.
        lease_ttl_s=1200.0,
        # — opt-in surfaces off by default (the Playwright/DB MCP + net-allowlist are later slices) —
        mcp=False,
        plugins=False,
        env=(),
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # UNRESTRICTED within the isolated worktree: it must run installs/builds/tests (arbitrary
        # commands) dream otherwise gates behind an interactive approval the kernel can't supply.
        # dream's credential guard, command-deny list, and worktree confinement still apply.
        sandbox=SandboxTier.UNRESTRICTED,
        # — subagents (Tier-1, role-owned) —
        # The §06 verification swarm: the Test-Author writes the FAILING tests first, independent of
        # the code (TDD 'pre'); the API-Verifier boots the built service and probes it over real HTTP
        # ('live', proving it RUNS); the Code-Reviewer red-teams the diff for the prod-failure classes
        # tests miss (missing authz, N+1, injection, …). Each is capability-minimised to a subset of
        # Bex's tools and returns a typed, runtime-validated verdict.
        subagents=(TEST_AUTHOR_SUBAGENT, API_VERIFIER_SUBAGENT, CODE_REVIEWER_SUBAGENT),
    )


__all__ = ["backend_engineer_manifest"]
