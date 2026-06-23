"""The Manager's dream-harness manifest — every ``build_harness`` component, in one place.

A Manager is a **ledger-writer**: its leverage is the capability tools that decompose and dispatch
work. Each field below names the dream component it drives.

M3 Slice 1 ships ``decompose`` (bulk fan-out). Slice 2 adds bounded integrate actions:
``submit_task`` for one follow-up and ``assign_task`` for one reroute. The
:class:`~chorus_harness.EmployeeHarnessFactory` registers these as model-callable chorus capability
tools bound to the org ledger.
"""

from __future__ import annotations

from chorus.roles._manifest import MemoryScope, PermissionMode, RoleManifest
from chorus_employee.manager._brief import MANAGER_BRIEF


def manager_manifest() -> RoleManifest:
    """The complete harness identity of a Manager (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=MANAGER_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        # ACCEPT_EDITS so the manager can author the ONE file it owns — the AGENTS.md contract — without
        # an interactive approval the kernel can't supply (the posture the PM uses for its plan doc). The
        # manager builds NO deliverable; this write surface exists solely for the cross-child contract
        # spec 15 §4.1 requires it to author before it may fan work out.
        permission_mode=PermissionMode.ACCEPT_EDITS,
        # — build_harness(registry=…) — manager capabilities + read/write the contract —
        tools=("read_file", "write_file", "decompose", "submit_task", "assign_task"),
        # — build_harness(memory=…) — a manager reasons across its team —
        memory_scope=MemoryScope.TEAM,
        # default sandbox=REPO_WRITE suffices: the manager writes AGENTS.md but runs no commands.
    )


__all__ = ["manager_manifest"]
