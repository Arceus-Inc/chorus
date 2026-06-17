"""LanderRegistry — the outcome-landing seam (spec 04 §2, spec 09 §4).

A passed beat must *land* its deliverable as a reviewable artifact, and *what* lands is role-specific
(an Engineer lands a PR, a Reviewer a verdict, a PM a doc). This registry maps a role's
``outcome_kind`` to its :class:`OutcomeLander`, so the kernel dispatches landing generically: adding an
employee that lands a new kind of artifact registers a lander here — no scheduler change (spec 09 §1).

Mirrors :class:`~chorus.roles.RoleRegistry`: built at the composition root, injected into the
:class:`~chorus.heartbeat.Scheduler`. Core, dream-free.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

    from chorus.outcomes._lander import OutcomeLander


class LanderRegistry:
    """An ``outcome_kind -> OutcomeLander`` map the kernel lands passed beats through."""

    def __init__(self) -> None:
        self._by_kind: dict[str, OutcomeLander] = {}

    @classmethod
    def from_landers(cls, landers: Iterable[OutcomeLander]) -> LanderRegistry:
        """Build a registry from an iterable of landers (keyed by each ``outcome_kind``)."""
        registry = cls()
        for lander in landers:
            registry.register(lander)
        return registry

    def register(self, lander: OutcomeLander) -> None:
        """Register ``lander`` under its ``outcome_kind`` (last registration wins)."""
        self._by_kind[lander.outcome_kind] = lander

    def get(self, outcome_kind: str) -> OutcomeLander | None:
        """The lander for ``outcome_kind``, or ``None`` when no employee lands that kind yet."""
        return self._by_kind.get(outcome_kind)

    def __contains__(self, outcome_kind: object) -> bool:
        return outcome_kind in self._by_kind


__all__ = ["LanderRegistry"]
