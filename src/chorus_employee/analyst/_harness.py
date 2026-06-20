"""The Analyst's dream-harness manifest — every ``build_harness`` component, in one place.

An Analyst **reads context and writes a findings doc**: it needs the file-read and file-write surfaces
and a worktree it can write into, but no command execution or network. Each field below names the
dream component it drives.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    Isolation,
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.analyst._brief import ANALYST_BRIEF


def analyst_manifest() -> RoleManifest:
    """The complete harness identity of an Analyst (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=ANALYST_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        # ACCEPT_EDITS: the Analyst writes its findings doc autonomously — there is no human to approve
        # the edit, so file writes auto-apply (as the Engineer does), bounded by the sandbox below.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # — build_harness(registry=…) —
        # read to gather evidence, write to persist the findings; no command/git/network surface.
        tools=("read_file", "write_file"),
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — worktree containment (spec 04 §4) —
        isolation=Isolation.WORKTREE,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        # repo-write: may write files within its isolated worktree, but runs no commands and has no net.
        sandbox=SandboxTier.REPO_WRITE,
    )


__all__ = ["analyst_manifest"]
