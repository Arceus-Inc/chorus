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

from chorus.roles._subagent import SubagentSpec


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
class McpServerSpec:
    """One MCP server a role admits — projected to a ``.harness/mcp-allowlist.toml`` ``[[mcp]]`` entry.

    ``endpoint`` is the transport-prefixed target dream's allowlist parses: e.g.
    ``"stdio://npx @playwright/mcp --headless"`` for a stdio server (the command line after
    ``stdio://`` is shell-split into ``command`` + ``args``), or an ``https://…`` / ``ws://…`` URL for
    the http / ws transports. ``tools`` narrows the admitted tool coverage (empty = every advertised
    tool is admitted); ``tier_required`` names the tool tier the server's tools land at. Only meaningful
    on a role whose ``mcp`` flag is True — the allowlist is the authority, so an empty ``mcp_servers``
    admits nothing even when ``mcp`` is True. Frozen so the manifest stays hashable across async beats.
    """

    name: str
    endpoint: str
    transport: str = "stdio"
    tier_required: str = ""
    tools: tuple[str, ...] = ()


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
    max_sprints: int = (
        1  # per-beat sprint budget: 1 = one beat is one sprint (spec 05); a role that
    )
    # does multi-sprint work (an engineer build) widens this so a step finishes in a single beat
    working_memory: bool = False  # the in-task scratchpad memory tier
    wake_model: str | None = None  # a cheaper model for heartbeat/wake turns
    mcp: bool = False  # admit the working dir's MCP allowlist (opt-in)
    plugins: bool = False  # load the working dir's repo-local plugins (opt-in)
    # The MCP servers this role admits — projected to ``.harness/mcp-allowlist.toml`` at materialize
    # when ``mcp`` is True (the allowlist is the admission authority; empty here wires nothing). Carried
    # through overlays like the other engine scalars — a surface never widens it.
    mcp_servers: tuple[McpServerSpec, ...] = ()
    env: tuple[tuple[str, str], ...] = ()  # host-resolution env (e.g. DREAM_HOME); never secrets
    # — beat time budget — how long ONE beat of this role may run before it's cut off / reaped. A
    # research-heavy role (spawns a multi-minute web_research sweep in one uninterrupted call) needs
    # more than the org defaults, or the beat times out / its run lease is reaped mid-research. ``None``
    # inherits the composition-root default (factory ``timeout_s`` / scheduler ``lease_ttl_s``).
    beat_timeout_s: float | None = None  # DreamBeatRunner wall-clock per beat
    lease_ttl_s: float | None = (
        None  # scheduler run-lease TTL before the stale-run reaper claims it
    )
    # — build_harness(subagents=…) — Tier-1 role-owned subagents the employee may dispatch mid-beat
    # (dream's ``spawn_subagent``). Each subagent's tools are intersected with this role's toolset at
    # materialize, so a subagent can only ever narrow capability, never widen it (spec 06 §minimisation).
    subagents: tuple[SubagentSpec, ...] = ()
    # — build_harness(skill_registry=…) — a filesystem dir holding this role's ``<slug>/SKILL.md``
    # playbooks. The composition root discovers them into a skill registry the harness offers the
    # model (catalogue in the prompt + the ``skill`` tool loads bodies). ``None`` = no role skills.
    skills_root: str | None = None


# Dream ``run_task`` default sprint budget — craft roles should match so one beat can
# implement→verify→fix to green without waiting on re-dispatch (P0 #6).
DREAM_DEFAULT_MAX_SPRINTS = 10
# Composition-root fallback when a role manifest omits ``beat_timeout_s`` (the old 90s
# default was far too tight for any multi-turn craft beat).
DEFAULT_BEAT_TIMEOUT_S = 600.0


__all__ = [
    "DEFAULT_BEAT_TIMEOUT_S",
    "DREAM_DEFAULT_MAX_SPRINTS",
    "Isolation",
    "McpServerSpec",
    "MemoryScope",
    "PermissionMode",
    "RoleManifest",
    "SandboxTier",
]
