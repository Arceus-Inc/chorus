"""The role plugin — the primary extension point (spec 06 §2, spec 09 §1).

A **role** is the unit of heterogeneity, and it is exactly three things
(Corebelief §6)::

    Role = ( RoleManifest      # toolset + system prompt + permission mode
           , DoDGenerator      # intent -> typed Verifier  (spec 04)
           , OutcomeKind )     # what "landed" means for this role  (spec 04 §2)

A :class:`RolePlugin` wraps that triple with a unique registration slug.
Registering one adds an employee type the kernel never knew about — no
scheduler, ledger, or recovery change (the M4 proof). Registration is
fail-closed and idempotent (spec 09 §1): an unknown tool, an illegal enum, a
``dod_generator`` that doesn't return a typed :class:`Verifier`, or an
``outcome_kind`` with no registered lander all raise ``RolePluginInvalid``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from chorus.outcomes import Verifier
from chorus.roles._manifest import RoleManifest

# intent -> typed Verifier, evaluated at intake by the assignee's role (spec 04).
DoDGenerator = Callable[[str], Verifier]


@dataclass(frozen=True)
class Role:
    """The role triple (spec 06 §2) — manifest + DoD generator + outcome kind."""

    manifest: RoleManifest
    dod_generator: DoDGenerator
    outcome_kind: str


@dataclass(frozen=True)
class RolePlugin:
    """A registrable role: a unique slug + the :class:`Role` triple.

    Constructed flat (per the spec 09 §1 example) for ergonomics; ``role``
    exposes the underlying triple. ``replace=True`` is the explicit override that
    lets a slug re-register with a *different* definition (otherwise a
    ``RolePluginConflict``).
    """

    name: str
    manifest: RoleManifest
    dod_generator: DoDGenerator
    outcome_kind: str
    replace: bool = False

    @property
    def role(self) -> Role:
        return Role(self.manifest, self.dod_generator, self.outcome_kind)


__all__ = [
    "DoDGenerator",
    "Role",
    "RolePlugin",
]
