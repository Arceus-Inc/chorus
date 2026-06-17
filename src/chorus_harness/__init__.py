"""chorus_harness — the dream-backed harness composition layer (spec 06 §2, spec 10 §1).

The one place that turns an employee into a *running* dream harness: :class:`EmployeeHarnessFactory`
resolves a role to its tools/brief/permission/memory and builds the harness in the employee's
branch-isolated worktree. It is front-end-agnostic — the kernel ``tick``, the conversational ``chat``,
and any caller injecting a :class:`~chorus.heartbeat.BeatRunnerFor` into the facade all share it.

This layer owns the ``dream`` import (it is a composition package, sibling to ``chorus_cli``); the
``chorus`` core stays dream-free and binds to it only through the ``BeatRunner`` / ``BeatRunnerFor``
protocols.
"""

from __future__ import annotations

from chorus_harness._factory import (
    EmployeeHarness,
    EmployeeHarnessFactory,
    dream_tool_names,
    write_role_overlays,
    write_sandbox_config,
)

__all__ = [
    "EmployeeHarness",
    "EmployeeHarnessFactory",
    "dream_tool_names",
    "write_role_overlays",
    "write_sandbox_config",
]
