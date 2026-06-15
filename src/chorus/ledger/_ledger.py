"""The ledger facade (spec 01) — opens the store, applies migrations, composes the repos.

``SqliteLedger`` is the durable source of truth for "what work exists and where it is." The kernel
reads/writes only through the per-aggregate repos it exposes (B2.2); every transition is a durable
write. The same repo code runs on Postgres later behind the same ``Ledger`` shape (spec 12) — only
``open`` (connection setup) and the migration DDL are dialect-specific.
"""

from __future__ import annotations

import sqlite3
from typing import Protocol, runtime_checkable

from chorus.ledger._migrations import MigrationRunner
from chorus.ledger.migrations import MIGRATIONS
from chorus.ledger.repos import (
    ActivityRepo,
    ApprovalRepo,
    ArtifactRepo,
    ArtifactRevisionRepo,
    DecompositionClaimRepo,
    DependencyRepo,
    DodRepo,
    EmployeeRepo,
    GoalRepo,
    MessageRepo,
    RecoveryActionRepo,
    RunRepo,
    TaskRepo,
    WakeRepo,
)


@runtime_checkable
class Ledger(Protocol):
    """The durable store the scheduler reads and writes (spec 01) — the swappable seam.

    Implemented by :class:`SqliteLedger` now and a Postgres-backed ledger in Arceus (spec 12);
    the kernel depends on this shape, never on a concrete driver.
    """

    employees: EmployeeRepo
    goals: GoalRepo
    tasks: TaskRepo
    decomposition_claims: DecompositionClaimRepo
    dependencies: DependencyRepo
    wakes: WakeRepo
    messages: MessageRepo
    approvals: ApprovalRepo
    activity: ActivityRepo
    recovery_actions: RecoveryActionRepo
    runs: RunRepo
    dod: DodRepo
    artifacts: ArtifactRepo
    artifact_revisions: ArtifactRevisionRepo

    def schema_version(self) -> str | None: ...

    def close(self) -> None: ...


class SqliteLedger:
    """The file-backed default :class:`Ledger` (spec 01, spec 12).

    ``open`` connects, enables foreign keys, applies any pending migrations (the applied-set runner,
    spec 01 §schema-versioning), and wires one repo per aggregate onto the shared connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._runner = MigrationRunner(MIGRATIONS)
        self.employees = EmployeeRepo(conn)
        self.goals = GoalRepo(conn)
        self.tasks = TaskRepo(conn)
        self.decomposition_claims = DecompositionClaimRepo(conn)
        self.dependencies = DependencyRepo(conn)
        self.wakes = WakeRepo(conn)
        self.messages = MessageRepo(conn)
        self.approvals = ApprovalRepo(conn)
        self.activity = ActivityRepo(conn)
        self.recovery_actions = RecoveryActionRepo(conn)
        self.runs = RunRepo(conn)
        self.dod = DodRepo(conn)
        self.artifacts = ArtifactRepo(conn)
        self.artifact_revisions = ArtifactRevisionRepo(conn)

    @classmethod
    def open(cls, db_path: str) -> SqliteLedger:
        """Open (creating + migrating) the ledger at ``db_path`` (use ``":memory:"`` for tests)."""
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        ledger = cls(conn)
        ledger._runner.apply(conn)
        return ledger

    def schema_version(self) -> str | None:
        """The highest applied migration id — presentation only (spec 01 §schema-versioning)."""
        return self._runner.display_version(self._conn)

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "Ledger",
    "SqliteLedger",
]
