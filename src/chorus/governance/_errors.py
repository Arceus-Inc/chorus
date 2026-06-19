"""The governance error hierarchy (§5 governance).

A single base so callers (CLI, kernel) catch one type. The resolver, registry, and handlers each raise
a more specific subclass, but all are :class:`GovernanceError`.
"""

from __future__ import annotations


class GovernanceError(RuntimeError):
    """A governance operation that cannot proceed."""


__all__ = ["GovernanceError"]
