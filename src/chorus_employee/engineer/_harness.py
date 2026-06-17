"""The Engineer's dream-harness manifest — every ``build_harness`` component, in one place.

This module is the literal answer to "what is an Engineer to dream?": a single
:class:`~chorus.roles.RoleManifest` whose every field maps to a knob the composition root
feeds :func:`dream.build_harness` (or writes as a per-role overlay). Each line below names
the dream component it drives, so the whole harness config reads top to bottom.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.engineer._brief import ENGINEER_BRIEF


def engineer_manifest() -> RoleManifest:
    """The complete harness identity of an Engineer (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=ENGINEER_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        permission_mode=PermissionMode.ACCEPT_EDITS,  # → overlay permission_mode (may write edits)
        # — build_harness(registry=…) —
        tools=("read_file", "write_file", "run_command", "git"),  # the wire toolset
        disallowed_tools=(),  # nothing additionally denied at the role level
        # — build_harness(skills=…) —
        skills=(),  # no Engineer skill playbooks yet → skills toggle stays off (follow-up)
        # — build_harness(memory=…) + working_memory —
        memory_scope=MemoryScope.PROJECT,  # reads/writes the project memory partition
        working_memory=True,  # keeps an in-task scratchpad across turns
        # — build_harness(model=…) / per-role model —
        model=None,  # None → the deployment model the composition root supplies
        wake_model=None,  # no cheaper wake model override
        # — build_harness(max_turns=…) —
        max_turns=12,  # coding is multi-step; a deeper budget than dream's default 8
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
    )


__all__ = ["engineer_manifest"]
