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
        # DEFAULT (not PLAN): the reviewer must be able to call its one mutating tool, ``submit_verdict``.
        # Its read-only-ness is enforced structurally — no file-writing tools below + the READ_ONLY
        # sandbox tier — so it can record a verdict but can never touch the work under review.
        permission_mode=PermissionMode.DEFAULT,
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
