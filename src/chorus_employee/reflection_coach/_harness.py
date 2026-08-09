"""The Reflection Coach's isolated, read-only harness configuration."""

from __future__ import annotations

from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, RoleManifest, SandboxTier
from chorus_employee.reflection_coach._brief import REFLECTION_COACH_BRIEF


def reflection_coach_manifest() -> RoleManifest:
    """A coach can inspect evidence and propose; it has no edit or delivery authority."""
    return RoleManifest(
        system_prompt=REFLECTION_COACH_BRIEF,
        tools=("read_file", "repo_search", "memory_search", "memory_get", "recall"),
        disallowed_tools=("comment",),
        permission_mode=PermissionMode.PLAN,
        memory_scope=MemoryScope.COMPANY,
        isolation=Isolation.WORKTREE,
        sandbox=SandboxTier.READ_ONLY,
        max_turns=8,
        max_sprints=1,
    )


__all__ = ["reflection_coach_manifest"]
