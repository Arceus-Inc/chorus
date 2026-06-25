"""The PM's dream-harness manifest — every ``build_harness`` component, in one place.

A PM **writes a plan doc**: it needs the file-write surface and a worktree it can write into, but no
command execution or network. Each field below names the dream component it drives.
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
        # write to persist the plan; no read/command/git/network surface. PM tasks are often created
        # specifically because the target plan is missing, so read probes are more harmful than useful.
        tools=("write_file",),
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # repo-write: may write files within its isolated worktree, but runs no commands and has no net.
        sandbox=SandboxTier.REPO_WRITE,
    )


__all__ = ["pm_manifest"]
