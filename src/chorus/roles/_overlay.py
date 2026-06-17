"""Overlay manifest resolution (spec 06 §2) — narrower-wins, capability is monotone.

A role is resolved by *layering*, never by class inheritance::

    base manifest  →  employee override  →  task/run policy

Each layer can only **narrow** capability — drop a tool, tighten the permission mode,
restrict the memory scope, escalate isolation — mirroring ``compute_minimum_toolset``'s
intersection (spec 05 §3). An overlay that tries to *widen* (add a tool the base lacks,
loosen a mode, broaden a scope) is silently a no-op, so no resolution order can ever
escalate privilege. ``disallowed_tools`` always wins over the allow-list.

The capability fields combine by commutative operations (intersection / union / min / max),
so the resolved capability is **order-independent**. Only ``system_prompt`` — not a
capability — is last-writer-wins.
"""

from __future__ import annotations

from dataclasses import dataclass

from chorus.roles._manifest import Isolation, MemoryScope, PermissionMode, RoleManifest

# Restrictiveness ranks: a higher number is *more* restrictive, so narrowing takes the max.
_PERMISSION_RESTRICTIVENESS: dict[PermissionMode, int] = {
    PermissionMode.DONT_ASK: 0,
    PermissionMode.ACCEPT_EDITS: 1,
    PermissionMode.DEFAULT: 2,
    PermissionMode.PLAN: 3,
}

# Memory breadth: a higher number is *wider*, so narrowing takes the min.
_SCOPE_BREADTH: dict[MemoryScope, int] = {
    MemoryScope.PRIVATE: 0,
    MemoryScope.PROJECT: 1,
    MemoryScope.TEAM: 2,
    MemoryScope.COMPANY: 3,
}

# Isolation containment: a higher number is *more* isolated, so narrowing takes the max.
_ISOLATION_CONTAINMENT: dict[Isolation, int] = {
    Isolation.WORKTREE: 0,
    Isolation.REMOTE: 1,
}


@dataclass(frozen=True)
class ManifestOverlay:
    """A sparse narrowing layer over a :class:`RoleManifest` (spec 06 §2).

    Every field is optional: ``None`` (or the empty ``disallowed_tools`` default) means
    *do not touch this dimension*. A set field can only narrow — it never widens the base.

    - ``tools`` / ``skills``: intersected with the running allow-set (can only remove).
    - ``disallowed_tools``: unioned in (always adds denies; deny beats allow).
    - ``permission_mode``: applied only if *more* restrictive than the running mode.
    - ``memory_scope``: applied only if *narrower* than the running scope.
    - ``isolation``: applied only if *more* isolated than the running isolation.
    - ``system_prompt``: a plain override (not a capability) — last non-``None`` wins.
    """

    system_prompt: str | None = None
    tools: tuple[str, ...] | None = None
    disallowed_tools: tuple[str, ...] = ()
    skills: tuple[str, ...] | None = None
    permission_mode: PermissionMode | None = None
    memory_scope: MemoryScope | None = None
    isolation: Isolation | None = None


def resolve_manifest(base: RoleManifest, *overlays: ManifestOverlay) -> RoleManifest:
    """Fold ``overlays`` onto ``base``, narrowing only (spec 06 §2).

    The result is monotone in capability: ``resolved.tools ⊆ base.tools``, the permission
    mode is at least as restrictive, the memory scope at least as narrow, and isolation at
    least as contained — regardless of overlay order.
    """
    allow = set(base.tools)
    deny = list(base.disallowed_tools)
    skill_allow = set(base.skills)
    permission = base.permission_mode
    scope = base.memory_scope
    isolation = base.isolation
    system_prompt = base.system_prompt

    for overlay in overlays:
        if overlay.tools is not None:
            allow &= set(overlay.tools)
        for tool in overlay.disallowed_tools:
            if tool not in deny:
                deny.append(tool)
        if overlay.skills is not None:
            skill_allow &= set(overlay.skills)
        if overlay.permission_mode is not None and _more_restrictive(
            overlay.permission_mode, permission
        ):
            permission = overlay.permission_mode
        if overlay.memory_scope is not None and _narrower(overlay.memory_scope, scope):
            scope = overlay.memory_scope
        if overlay.isolation is not None and _more_isolated(overlay.isolation, isolation):
            isolation = overlay.isolation
        if overlay.system_prompt is not None:
            system_prompt = overlay.system_prompt

    denied = set(deny)
    tools = tuple(t for t in base.tools if t in allow and t not in denied)
    skills = tuple(s for s in base.skills if s in skill_allow)
    return RoleManifest(
        system_prompt=system_prompt,
        tools=tools,
        disallowed_tools=tuple(deny),
        skills=skills,
        permission_mode=permission,
        memory_scope=scope,
        isolation=isolation,
        # Engine scalars are policy, not capability — carried through unchanged (no overlay narrows
        # them today; an override layer for them would extend ManifestOverlay, not this fold).
        model=base.model,
        max_turns=base.max_turns,
        working_memory=base.working_memory,
        wake_model=base.wake_model,
        mcp=base.mcp,
        plugins=base.plugins,
        env=base.env,
    )


def _more_restrictive(candidate: PermissionMode, current: PermissionMode) -> bool:
    return _PERMISSION_RESTRICTIVENESS[candidate] > _PERMISSION_RESTRICTIVENESS[current]


def _narrower(candidate: MemoryScope, current: MemoryScope) -> bool:
    return _SCOPE_BREADTH[candidate] < _SCOPE_BREADTH[current]


def _more_isolated(candidate: Isolation, current: Isolation) -> bool:
    return _ISOLATION_CONTAINMENT[candidate] > _ISOLATION_CONTAINMENT[current]


__all__ = ["ManifestOverlay", "resolve_manifest"]
