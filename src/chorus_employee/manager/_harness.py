"""The Manager's dream-harness manifest — every ``build_harness`` component, in one place.

A Manager is a **ledger-writer**: its leverage is the capability tools that decompose and dispatch
work (``submit_task`` / ``assign_task``). Each field below names the dream component it drives.

NOTE (M3): the capability tools declared here are not yet registered into the dream harness — the
:class:`~chorus_harness.EmployeeHarnessFactory` only maps dream built-ins today, so a manager beat
currently receives only ``read_file``. Wiring chorus capability tools into the harness is the M3
foundation; this manifest declares the *intended* toolset.
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
        # — build_harness(registry=…) — ledger-write capability tools (harness registration is M3) —
        tools=("read_file", "submit_task", "assign_task"),
        # — build_harness(memory=…) — a manager reasons across its team —
        memory_scope=MemoryScope.TEAM,
    )


__all__ = ["manager_manifest"]
