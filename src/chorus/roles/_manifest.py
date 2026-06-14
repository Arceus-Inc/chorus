"""The chorus-level role manifest (spec 06 §2).

A role's standing contract: the system prompt, the tool allow/deny-lists, the
permission mode, and the memory scope an employee of this role runs under. This
is chorus's *org-role* manifest (Engineer, Reviewer, Manager, PM, Analyst) —
distinct from dream's intra-task ``RoleManifest`` (planner/generator/evaluator),
which a beat uses internally.

Resolution is **overlay, not inheritance** (spec 06 §2): ``base → role manifest
→ employee override → task/run policy``, narrower-wins, each layer only able to
*narrow* capability — mirroring ``compute_minimum_toolset``'s intersection so
privilege is monotone and can never be escalated by resolution order.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionMode(StrEnum):
    """Permission gate posture (subset of dream's; no ``bypassPermissions``)."""

    DEFAULT = "default"
    ACCEPT_EDITS = "acceptEdits"
    PLAN = "plan"
    DONT_ASK = "dontAsk"


class MemoryScope(StrEnum):
    """Which memory partition the role reads/writes (spec 07 §1)."""

    PRIVATE = "private"
    PROJECT = "project"
    TEAM = "team"
    COMPANY = "company"


class Isolation(StrEnum):
    """Where the beat's workspace lives (spec 04 §4 containment)."""

    WORKTREE = "worktree"
    REMOTE = "remote"


@dataclass(frozen=True)
class RoleManifest:
    """One org-role's standing contract.

    Tuples (not lists) on the collection fields so the manifest is hashable and
    safe to share across async beats; ``tools`` is the explicit allow-list
    (no ``None`` "all" escape hatch at the org level — a role always declares).
    """

    system_prompt: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    memory_scope: MemoryScope = MemoryScope.PROJECT
    isolation: Isolation = Isolation.WORKTREE


__all__ = [
    "Isolation",
    "MemoryScope",
    "PermissionMode",
    "RoleManifest",
]
