"""Shared swarm-role registry — reusable Tier-2 capability agents (spec GM §4, §13).

dream already runs a bounded, depth-capped, ephemeral intra-task swarm. A role's *Tier-1* specialists
are domain-specific (they live in that role's plugin), but *Tier-2* capability agents — the
Query Orchestrator that plans which sources to hit, writes the SQL, and iterates — are role-agnostic
reasoning any employee's swarm should be able to pull in. This registry is their home: the agentic
counterpart to the shared tool registry, kernel-level and inherited by the whole workforce.

A :class:`SwarmRole` is a **capability-minimized overlay** (narrower-wins, spec 06 §2): it only ever
*drops* tools / tightens scope, never widens, so spawning one can never escalate privilege past the
parent. Registration is fail-closed + idempotent, mirroring :class:`~chorus.roles.RoleRegistry`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from chorus.errors import SwarmRoleConflict, SwarmRoleInvalid


@dataclass(frozen=True)
class SwarmRole:
    """A reusable Tier-2 capability agent — role-agnostic reasoning a swarm pulls in (spec GM §4).

    ``tools`` is its capability-minimized allow-list (the deterministic primitives it composes over,
    e.g. ``warehouse.query``); ``skills`` is the authored know-how it consults (e.g. query patterns).
    The rule (spec GM §4): judgment ⇒ an agent + skill; mechanical ⇒ a tool — so a SwarmRole always
    declares at least one tool to act through.
    """

    name: str
    description: str
    tools: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()
    spawned_by: tuple[str, ...] = field(default_factory=tuple)


class SwarmRoleRegistry:
    """An in-memory ``name -> SwarmRole`` map, validated fail-closed at registration (spec GM §4)."""

    def __init__(self) -> None:
        self._roles: dict[str, SwarmRole] = {}

    @classmethod
    def from_roles(cls, roles: Iterable[SwarmRole]) -> SwarmRoleRegistry:
        """Build a registry and register every role through the validated path."""
        registry = cls()
        for role in roles:
            registry.register(role)
        return registry

    # -- reads ----------------------------------------------------------------

    def get(self, name: str) -> SwarmRole:
        return self._roles[name]

    def names(self) -> tuple[str, ...]:
        return tuple(self._roles)

    def __contains__(self, name: object) -> bool:
        return name in self._roles

    def __len__(self) -> int:
        return len(self._roles)

    # -- writes ---------------------------------------------------------------

    def register(self, role: SwarmRole, *, replace: bool = False) -> None:
        """Validate, then register the role — fail-closed + idempotent (spec GM §4)."""
        self._validate(role)
        existing = self._roles.get(role.name)
        if existing is not None and not replace:
            if existing == role:
                return  # idempotent — an identical definition is a harmless no-op
            raise SwarmRoleConflict(
                f"swarm role {role.name!r} already registered with a different definition; "
                "pass replace=True to override"
            )
        self._roles[role.name] = role

    # -- validation -----------------------------------------------------------

    @staticmethod
    def _validate(role: SwarmRole) -> None:
        if not role.name or not role.name.strip():
            raise SwarmRoleInvalid("swarm role name must be a non-empty slug")
        if not role.description or not role.description.strip():
            raise SwarmRoleInvalid(f"swarm role {role.name!r} must carry a description")
        if not role.tools:
            raise SwarmRoleInvalid(
                f"swarm role {role.name!r} declares no tools — a capability agent must act through "
                "at least one tool (spec GM §4)"
            )


__all__ = ["SwarmRole", "SwarmRoleRegistry"]
