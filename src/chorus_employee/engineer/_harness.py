"""The Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

This module is the literal answer to "what is an Engineer to dream?": a single
:class:`~chorus.roles.RoleManifest` whose every field maps to a knob the composition root
feeds :func:`dream.build_harness` (or writes as a per-role overlay). Each line below names
the dream component it drives, so the whole harness config reads top to bottom.
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
from chorus_employee.engineer._brief import ENGINEER_BRIEF

_SKILLS_ROOT = str(Path(__file__).parent / "skills")


def engineer_manifest() -> RoleManifest:
    """The complete harness identity of an Engineer (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=ENGINEER_BRIEF,  # → .harness/roles/{planner,generator,evaluator}.toml
        permission_mode=PermissionMode.ACCEPT_EDITS,  # → overlay permission_mode (may write edits)
        # — build_harness(registry=…) —
        tools=(
            "read_file",
            "write_file",
            "run_command",
            "execute_code",
            "git",
            "todo_write",
            "skill",
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
        ),  # the wire toolset, including Dream's durable + task memory surfaces
        disallowed_tools=(),  # nothing additionally denied at the role level
        # — build_harness(skills=…) — shared cross-beat skills merge in via factory —
        skills=("cross-beat-resume", "cross-beat-recall"),
        skills_root=_SKILLS_ROOT,
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,  # reads/writes the project memory partition
        working_memory=True,  # keeps an in-task scratchpad across turns
        # — build_harness(model=…) / per-role model —
        model=None,  # None → the deployment model the composition root supplies
        wake_model=None,  # no cheaper wake model override
        # — build_harness(max_turns=…) —
        max_turns=12,  # coding is multi-step; a deeper budget than dream's default 8
        # — per-beat sprint budget (spec 05) —
        # A build is multi-sprint (dream needs up to NEEDS_CHANGES_LIMIT sprints to land a step): widen
        # the budget so one engineer beat runs the build to pass, instead of stopping after one sprint
        # with `needs-changes` and depending on re-dispatch to continue.
        max_sprints=DREAM_DEFAULT_MAX_SPRINTS,
        # — build_harness(mcp=…) / build_harness(plugins=…) —
        mcp=False,  # admit the working dir's MCP allowlist only when explicitly enabled
        plugins=False,  # load repo-local plugins only when explicitly enabled
        # — build_harness(env=…) —
        env=(),  # host-resolution env only (e.g. DREAM_HOME); never carries secrets
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # unrestricted *within the isolated worktree*: the engineer must run tests/builds (arbitrary
        # commands), which dream otherwise gates behind an interactive approval the kernel can't supply.
        # dream's credential guard, command-deny list, and worktree confinement still apply.
        sandbox=SandboxTier.UNRESTRICTED,
        # — beat time budget — code craft can hold install/build/test cycles (P0 #6) —
        beat_timeout_s=1200.0,
        lease_ttl_s=1500.0,
    )


__all__ = ["engineer_manifest"]
