"""The Manager's dream-harness manifest — every ``build_harness`` component, in one place.

A Manager is a **ledger-writer**: its leverage is the capability tools that decompose and dispatch
work. Each field below names the dream component it drives.

M3 Slice 1 ships ``decompose`` (bulk fan-out): the
:class:`~chorus_harness.EmployeeHarnessFactory` registers it as a model-callable chorus capability
tool bound to the org ledger. ``submit_task`` (incremental add) and ``assign_task`` (route / reassign)
follow in Slice 2.
"""

from __future__ import annotations

from chorus.roles._manifest import MemoryScope, PermissionMode, RoleManifest
from chorus_employee.manager._brief import MANAGER_BRIEF


def manager_manifest() -> RoleManifest:
    """The complete harness identity of a Manager (spec 06 §2 → dream ``build_harness``)."""
    return RoleManifest(
        # — per-role overlay —
        system_prompt=MANAGER_BRIEF,  # → roles/{planner,generator,evaluator}.toml system_prompt
        permission_mode=PermissionMode.DEFAULT,
        # — build_harness(registry=…) — the chorus decompose capability + a read surface (M3 Slice 1) —
        tools=("read_file", "decompose"),
        # — build_harness(memory=…) — a manager reasons across its team —
        memory_scope=MemoryScope.TEAM,
    )


__all__ = ["manager_manifest"]
