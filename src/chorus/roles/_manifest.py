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


class SandboxTier(StrEnum):
    """The role's trust posture — how much its tools may do (spec 04 §4; dream's sandbox tiers).

    Values are dream's wire strings (so the materializer writes them straight into
    ``.harness/sandbox.toml``). Ordered by capability: a read-only role can't write; a ``repo-write``
    role writes within its worktree; ``unrestricted`` additionally lets it run arbitrary commands
    (tests, builds) — needed for an autonomous engineer, since dream otherwise gates a non-path command
    behind an interactive approval the kernel can't supply. Even ``unrestricted`` keeps dream's
    credential guard, command-deny list, and worktree confinement (a deliberate, doubly-gated act).
    """

    READ_ONLY = "read-only"
    REPO_WRITE = "repo-write"
    REPO_WRITE_NET = "repo-write+net-allowlist"
    UNRESTRICTED = "unrestricted"


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
    sandbox: SandboxTier = SandboxTier.REPO_WRITE  # the role's trust posture (dream sandbox tier)
    # Engine scalars — the non-capability ``build_harness`` knobs (carried through overlays).
    model: str | None = None  # None → use the deployment model the composition root supplies
    max_turns: int = 8  # dream's per-role turn budget default
    max_sprints: int = 1  # per-beat sprint budget: 1 = one beat is one sprint (spec 05); a role that
    # does multi-sprint work (an engineer build) widens this so a step finishes in a single beat
    working_memory: bool = False  # the in-task scratchpad memory tier
    wake_model: str | None = None  # a cheaper model for heartbeat/wake turns
    mcp: bool = False  # admit the working dir's MCP allowlist (opt-in)
    plugins: bool = False  # load the working dir's repo-local plugins (opt-in)
    env: tuple[tuple[str, str], ...] = ()  # host-resolution env (e.g. DREAM_HOME); never secrets
    # Subagent declarations (Tier-1, role-owned): the subagents this role may spawn mid-beat.
    # Each entry is projected onto dream's SubagentSet at materialize time. Empty → no subagents.
    subagents: tuple[SubagentDecl, ...] = ()


@dataclass(frozen=True)
class SubagentDecl:
    """Chorus-side subagent declaration — projected onto dream's ``Subagent`` at materialize.

    Declared on the role manifest (Tier-1). Capability-minimized: ``tools`` must be a subset
    of the parent role's tools (enforced at projection time by narrower-wins intersection).
    """

    name: str
    description: str
    tools: tuple[str, ...]
    system_prompt: str | None = None
    max_turns: int = 4
    depth: int = 1


__all__ = [
    "Isolation",
    "MemoryScope",
    "PermissionMode",
    "RoleManifest",
    "SandboxTier",
    "SubagentDecl",
]
