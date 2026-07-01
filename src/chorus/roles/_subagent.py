"""``SubagentSpec`` — a role-owned subagent declaration (chorus org-level, dream-free).

A role may declare Tier-1 **subagents**: bounded, capability-minimized specialists an employee can
dispatch *within one beat* (dream's ``spawn_subagent`` tool). This is the chorus, dream-free shape —
just the fields a beat needs — mirroring how :class:`RoleManifest` stays dream-free and the composition
root (``chorus_harness``) projects it onto dream's ``Subagent`` / ``SubagentSet`` at materialize time.

Capability minimisation (spec 06 §"capability minimisation"): a subagent's ``tools`` must be a subset
of the parent role's toolset — the projection intersects them, so a subagent can only ever *narrow*,
never widen, what its parent can do.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SubagentSpec:
    """One role-owned subagent template (Tier-1), dream-free.

    ``tools`` are *chorus* tool names (the same vocabulary as ``RoleManifest.tools``); the composition
    root maps them to dream names and intersects with the parent's live toolset. ``model`` lets a
    cheap specialist run on a smaller model than the parent; ``None`` inherits the parent's model.
    """

    name: str
    description: str
    tools: tuple[str, ...] = ()
    model: str | None = None
    max_turns: int = 6

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SubagentSpec.name must be a non-empty slug")
        if not self.description or not self.description.strip():
            raise ValueError(f"SubagentSpec {self.name!r} must carry a non-empty description")
        if isinstance(self.tools, str):
            raise TypeError("SubagentSpec.tools must be a sequence of strings, not a bare string")


__all__ = ["SubagentSpec"]
