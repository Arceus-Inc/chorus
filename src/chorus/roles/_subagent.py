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
from enum import StrEnum
from pathlib import Path
from typing import Any


class SubagentExecutionMode(StrEnum):
    """Whether a specialist co-writes or receives an isolated delegation inlet."""

    DELEGATE = "delegate"
    INLINE = "inline"


@dataclass(frozen=True)
class SubagentSpec:
    """One role-owned subagent template (Tier-1), dream-free.

    ``tools`` are *chorus* tool names (the same vocabulary as ``RoleManifest.tools``); the composition
    root maps them to dream names and intersects with the parent's live toolset. ``model`` lets a
    cheap specialist run on a smaller model than the parent; ``None`` inherits the parent's model.

    ``output_schema`` is an optional JSON-schema dict the subagent's final message is validated against
    at runtime: the composition root passes it to dream, whose inline executor coerces + validates the
    output, runs a bounded reformat loop on failure, and fails open with a warning. ``None`` = free-text
    return (no enforcement).
    """

    name: str
    description: str
    tools: tuple[str, ...] = ()
    model: str | None = None
    max_turns: int = 6
    execution_mode: SubagentExecutionMode = SubagentExecutionMode.DELEGATE
    output_schema: dict[str, Any] | None = None
    evidence_path: str | None = None
    evidence_claim: dict[str, Any] | None = None
    evidence_read_only: bool = False
    spawnable: tuple[SubagentSpec, ...] = ()
    """Tier-2 subagents THIS spec may itself dispatch (depth-2). Empty (default) = a leaf. The
    composition root projects these onto dream's ``Subagent.spawnable``, intersecting each with this
    spec's own tools so a grandchild can only narrow. Requires ``spawn_subagent`` in ``tools``."""

    def __post_init__(self) -> None:
        if not self.name or not self.name.strip():
            raise ValueError("SubagentSpec.name must be a non-empty slug")
        if not self.description or not self.description.strip():
            raise ValueError(f"SubagentSpec {self.name!r} must carry a non-empty description")
        if isinstance(self.tools, str):
            raise TypeError("SubagentSpec.tools must be a sequence of strings, not a bare string")
        if (self.evidence_path is None) != (self.evidence_claim is None):
            raise ValueError(
                f"SubagentSpec {self.name!r} evidence_path and evidence_claim must be set together"
            )
        if self.evidence_read_only and self.evidence_path is None:
            raise ValueError(
                f"SubagentSpec {self.name!r} cannot be evidence_read_only without evidence"
            )
        if self.evidence_path is not None:
            evidence_path = Path(self.evidence_path)
            if evidence_path.is_absolute() or ".." in evidence_path.parts:
                raise ValueError(
                    f"SubagentSpec {self.name!r} evidence_path must stay within the worktree"
                )
            if not self.evidence_claim:
                raise ValueError(f"SubagentSpec {self.name!r} evidence_claim must not be empty")
        if self.spawnable and "spawn_subagent" not in self.tools:
            raise ValueError(
                f"SubagentSpec {self.name!r} declares spawnable children but lacks 'spawn_subagent' "
                "in its tools — it could never dispatch them"
            )


__all__ = ["SubagentExecutionMode", "SubagentSpec"]
