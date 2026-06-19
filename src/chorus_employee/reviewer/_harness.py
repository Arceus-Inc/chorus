"""The Reviewer's dream-harness manifest — every ``build_harness`` component, in one place.

A Reviewer is **read-only everywhere**: it inspects work and renders a verdict, never mutating. Each
field below names the dream component it drives.
"""

from __future__ import annotations

from chorus.roles._manifest import (
    MemoryScope,
    PermissionMode,
    RoleManifest,
    SandboxTier,
)
from chorus_employee.reviewer._brief import REVIEWER_BRIEF


def reviewer_manifest() -> RoleManifest:
    """The complete harness identity of a Reviewer (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=REVIEWER_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        permission_mode=PermissionMode.PLAN,  # plan-only: it never writes edits
        # — build_harness(registry=…) —
        # read-only on the filesystem; ``submit_verdict`` is its one capability — it mutates only the
        # ledger DoD verdict, never the work under review (Path A, M3 load-bearing Reviewer).
        tools=("read_file", "submit_verdict"),
        # — build_harness(memory=…) —
        memory_scope=MemoryScope.PROJECT,
        # — trust posture (spec 04 §4) → .harness/sandbox.toml —
        sandbox=SandboxTier.READ_ONLY,  # a reviewer never mutates — read-only trust posture
    )


__all__ = ["reviewer_manifest"]
