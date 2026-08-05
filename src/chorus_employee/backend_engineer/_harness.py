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
    DREAM_DEFAULT_MAX_SPRINTS,
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
        # Hermes-simple lean coding surface: implement with file/bash/todo; load skills on
        # demand; keep proof/safety tools. Ambient memory/lattice ritual tools demoted —
        # they burned turns without helping hard-ticket pass@1.
        tools=(
            "read_file",
            "write_file",
            "edit_file",
            "run_command",
            "execute_code",
            "git",
            "browser_run",
            "test_evidence",
            "test_red",
            "secret_scan",
            "code_quality",
            "skill",
            "todo_write",
            "spawn_subagent",
        ),
        disallowed_tools=(),
        # — build_harness(skills=…) / (skill_registry=…) — authored craft playbooks, loaded on demand
        # via the `skill` tool; discovered from this package's skills/ dir. The first is the
        # framework-agnostic quality-gate know-how behind the code_quality tool.
        skills=(
            "structuring-any-service",
            "verifying-any-stack",
            # Parent TDD cycle (Hermes-style): RED→GREEN→REFACTOR via tools; not a spawn ritual.
            "test-driven-development",
            # Suite shape companion for TDD / optional test_author.
            "testing-honeycomb-strategy",
            # §16 Slice 3 — the verification library's real-system methods (spec §11): a real datastore
            # under the integration core, spec-driven API conformance, and cross-service contracts.
            "testcontainers-integration",
            "property-testing-schemathesis",
            "contract-testing-pact",
            # the tests-are-real gate: inject faults, require the suite to KILL them, so a green
            # bundle proves the tests would go RED on a regression — not just that they pass now.
            "mutation-testing",
            # the safe-exit gate: a schema migration must round-trip (apply → roll back → re-apply)
            # against the real engine, so a bad deploy has a way out — not a forward-only one-way door.
            "migration-roundtrip",
        ),
        skills_root=_SKILLS_ROOT,
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,
        working_memory=True,  # a scratchpad across the implement → run → fix turns
        # — build_harness(model=…) —
        model=None,  # the deployment model the composition root supplies
        wake_model=None,
        # — build_harness(max_turns=…) — implement → install → run → test → fix is turn-hungry —
        max_turns=24,
        # — per-beat sprint budget: enough for needs-changes repair inside one Dream task
        # (Hermes-simple) without cold outer resubmits —
        max_sprints=max(DREAM_DEFAULT_MAX_SPRINTS, 6),
        # — wall-clock per beat (DreamBeatRunner) — the heaviest beat of any role: it BUILDS a running
        # service, INSTALLS its real quality tools (ruff/mypy — no gaming), BOOTS it, RESTARTS it
        # (durability proof), and runs the full test sandwich (test_author + api_verifier + test_evidence),
        # each spending real wall-clock (installs, server polls, sleeps, subprocesses) on top of many
        # model turns. The 90s default is far too tight; a correction sprint plus terminal independent
        # review can legitimately take 15-20 minutes without introducing a retry or resume.
        beat_timeout_s=1200.0,
        # — run-lease TTL — must OUTLIVE the beat's own wall-clock budget so the stale-run reaper never
        # claims a beat that is still legitimately running.
        lease_ttl_s=1500.0,
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
