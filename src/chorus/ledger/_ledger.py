"""The ledger seam + the SQLite default backend (spec 01, spec 03).

``Ledger`` is the durable source of truth for "what work exists and where it is."
Every task transition is a durable write; the scheduler reads eligibility from
here (B2.2). The default :class:`SqliteLedger` writes the SQLite ∩ Postgres
schema from spec 01 — including the **partial-unique crash-safety indexes** that
make self-spawned work exact-once at the database layer.

The two execution locks (``checkout_run_id`` / ``execution_run_id``) are
*enforced* on dream's coordination board; the ``task`` columns here are a
denormalised mirror for the scheduler's eligibility queries (spec 01 note).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from chorus.ledger._models import Task, TaskStatus


@runtime_checkable
class Ledger(Protocol):
    """The durable task store the scheduler reads and writes (spec 01)."""

    def submit(self, task: Task) -> Task:
        """Insert a task. Exact-once for self-spawned work via the origin indexes."""
        ...

    def get(self, task_id: str) -> Task:
        """Fetch one task by id."""
        ...

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        """Transition a task, stamping the matching ``*_at`` column."""
        ...

    def list_eligible(self, *, limit: int) -> list[Task]:
        """Tasks whose dependencies are all ``done`` and that have a queued path (spec 03 §3)."""
        ...

    def release_locks(self, task_id: str) -> None:
        """Compare-and-clear the two execution locks — terminal-only (spec 01 invariant 4)."""
        ...


class SqliteLedger:
    """The file-backed default ``Ledger`` (spec 01).

    On construction it applies the spec 01 DDL — the task/wake/routine/run/goal
    tables plus the partial-unique indexes that are the crash-safety contract.
    The Arceus/Postgres distribution swaps a Postgres-backed ``Ledger`` behind
    this same Protocol (spec 03 §5 multi-tick safety).
    """

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path

    @classmethod
    def open(cls, db_path: str) -> SqliteLedger:
        """Open (creating + migrating) the ledger at ``db_path``."""
        return cls(db_path)

    def submit(self, task: Task) -> Task:
        raise NotImplementedError("spec 01 Cluster A: insert + origin exact-once indexes")

    def get(self, task_id: str) -> Task:
        raise NotImplementedError("spec 01 Cluster A: fetch by id")

    def set_status(self, task_id: str, status: TaskStatus) -> None:
        raise NotImplementedError("spec 01 Cluster A: transition + timestamp")

    def list_eligible(self, *, limit: int) -> list[Task]:
        raise NotImplementedError("spec 03 §3: dependency-resolved + priority/age ordering")

    def release_locks(self, task_id: str) -> None:
        raise NotImplementedError("spec 01 invariant 4: compare-and-clear, terminal-only")


__all__ = [
    "Ledger",
    "SqliteLedger",
]
