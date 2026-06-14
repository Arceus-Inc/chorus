"""chorus's own contract layer — the swappable seams (spec 09 §4).

Everything binds to typed contracts, not concrete classes (B0.2). Alongside
``dream.contracts`` (the shared POSIX both chorus and the siblings code against),
chorus exposes its own: ``RolePlugin``, ``WakeQueue``, ``RoutineStore``,
``Verifier`` (the DoD), ``OutcomeLander`` (role-specific landing), and
``Inspector`` (the read model). Each has a default impl plus a swappable seam.

The siblings are **consumers, not forks** (spec 09 §4): horizon drives intake by
writing ``task``/``goal`` rows and reading the event stream; lattice swaps the
``MemoryWriter`` behind the ``MemoryStore``/``MemoryWriter`` split. Neither
imports chorus internals and chorus imports neither of them — they meet only at
these contracts + the shared data layer.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

# Re-exported chorus contracts (concrete shapes that *are* the seam).
from chorus.observability import Inspector
from chorus.outcomes import OutcomeLander, Verifier
from chorus.roles import RolePlugin


@runtime_checkable
class WakeQueue(Protocol):
    """The coalescing push inbox (spec 03 §2) — the durable wake seam.

    The default is the SQLite ``wake`` table; Arceus/Postgres swaps a
    ``SKIP LOCKED`` queue behind this same Protocol for multi-tick safety
    (spec 03 §5).
    """

    def enqueue(self, *, employee_id: str, reason: str, payload: dict[str, object]) -> None:
        """Enqueue a wake; coalesces on ``coalesce_key`` (spec 01 ``wake_queued_key_uq``)."""
        ...

    def claim(self, *, limit: int) -> list[object]:
        """Claim up to ``limit`` wakes in the deterministic sort order (spec 03 §3)."""
        ...

    def mark_done(self, wake_id: str) -> None:
        """Mark a claimed wake finished."""
        ...


@runtime_checkable
class RoutineStore(Protocol):
    """The cron store (spec 03 §4) — routines, triggers, and exact-once runs."""

    def due(self, now: object) -> list[object]:
        """Triggers whose ``next_run_at <= now`` and whose routine is active."""
        ...

    def claim_edge(self, trigger_id: str, *, expected_next_run_at: object) -> bool:
        """The double-fire guard — conditional ``next_run_at`` UPDATE (spec 01)."""
        ...


__all__ = [
    "Inspector",
    "OutcomeLander",
    "RolePlugin",
    "RoutineStore",
    "Verifier",
    "WakeQueue",
]
