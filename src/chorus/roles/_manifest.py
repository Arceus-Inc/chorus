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
    """One org-role's standing contract — the complete identity of a dream harness.

    Every field maps to a knob of the dream harness an employee of this role runs: the
    *capability* fields (``tools``/``disallowed_tools``/``skills``/``permission_mode``/
    ``memory_scope``/``isolation``) plus the *engine* scalars (``model``/``max_turns``/
    ``working_memory``/``wake_model``/``mcp``/``plugins``/``env``). Capability fields are
    subject to overlay narrowing (spec 06 §2); the scalars are policy, carried through.

    Tuples (not lists) on the collection fields — and ``env`` as a tuple of pairs — so the
    manifest is hashable and safe to share across async beats; ``tools`` is the explicit
    allow-list (no ``None`` "all" escape hatch at the org level — a role always declares).
    """

    system_prompt: str
    tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    memory_scope: MemoryScope = MemoryScope.PROJECT
    isolation: Isolation = Isolation.WORKTREE
    # Engine scalars — the non-capability ``build_harness`` knobs (carried through overlays).
    model: str | None = None  # None → use the deployment model the composition root supplies
    max_turns: int = 8  # dream's per-role turn budget default
    working_memory: bool = False  # the in-task scratchpad memory tier
    wake_model: str | None = None  # a cheaper model for heartbeat/wake turns
    mcp: bool = False  # admit the working dir's MCP allowlist (opt-in)
    plugins: bool = False  # load the working dir's repo-local plugins (opt-in)
    env: tuple[tuple[str, str], ...] = ()  # host-resolution env (e.g. DREAM_HOME); never secrets


__all__ = [
    "Isolation",
    "MemoryScope",
    "PermissionMode",
    "RoleManifest",
]
