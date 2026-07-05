"""The Backend Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

The Backend Engineer is the Engineer's structural twin (spec §02), so this manifest is a re-point of
the Engineer's: the same build-and-run toolset, the same ``UNRESTRICTED`` sandbox within an isolated
worktree (it must install packages and run arbitrary build/test commands), with a deeper turn budget
because the implement → run → test → fix loop is turn-hungry. It carries the ``test_evidence`` proof
primitive (§10) and the ``api_verifier`` subagent (§16 Slice 3 — an independent grader that boots the
built service and probes it over real HTTP); the net-allowlist refinement lands in a later slice.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.backend_engineer._brief import BACKEND_ENGINEER_BRIEF
from chorus_employee.backend_engineer._subagents import API_VERIFIER_SUBAGENT


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
            "memory_search",
            "memory_get",
            "working_memory_read",
            "working_memory_write",
            "working_memory_append",
            "memory_propose",
            # dispatch the api_verifier subagent mid-beat (§16 Slice 3) — the grader that boots the
            # built service and probes it over real HTTP; its tools narrow this set at materialize.
            "spawn_subagent",
        ),
        disallowed_tools=(),
        skills=(),  # the backend-craft skill library lands in a later slice
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
        # The API-Verifier: an independent grader the engineer spawns after the unit bundle is green,
        # to prove the service RUNS — it boots the built service on a real port and probes it over
        # HTTP, returning a typed ApiTestVerdict. Read + run + write only; it verifies, never fixes.
        subagents=(API_VERIFIER_SUBAGENT,),
    )


__all__ = ["backend_engineer_manifest"]
