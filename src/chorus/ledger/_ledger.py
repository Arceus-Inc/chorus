"""The ledger facade (spec 01) — opens the store, applies migrations, composes the repos.

``SqliteLedger`` is the durable source of truth for "what work exists and where it is." The kernel
reads/writes only through the per-aggregate repos it exposes (B2.2); every transition is a durable
write. The repo wiring and the cross-aggregate atomics live in :class:`~chorus.ledger._core.LedgerCore`
and are shared with :class:`~chorus.ledger.postgres.PostgresLedger` (spec 12) — only ``open``
(connection setup) and the migration DDL are dialect-specific.
"""

from __future__ import annotations

import sqlite3
from contextlib import AbstractContextManager
from typing import Protocol, runtime_checkable

from chorus.ledger._core import LedgerCore
from chorus.ledger._migrations import MigrationRunner
from chorus.ledger._models import (
    DecompositionClaim,
    DodStatus,
    Task,
    Wake,
)
from chorus.ledger.migrations import MIGRATIONS
from chorus.ledger.repos import (
    ActivityRepo,
    ApprovalRepo,
    ArtifactRepo,
    ArtifactRevisionRepo,
    BudgetIncidentRepo,
    BudgetPolicyRepo,
    ClaimRepo,
    CostEventRepo,
    DecisionRepo,
    DecompositionClaimRepo,
    DelegationContractRepo,
    DependencyRepo,
    DodRepo,
    EmployeeRepo,
    GoalRepo,
    ManagementProfileRepo,
    MessageRepo,
    MonitorRepo,
    RecoveryActionRepo,
    RoutineRepo,
    RoutineRevisionRepo,
    RoutineRunRepo,
    RoutineTriggerRepo,
    RunRepo,
    StaffingRequestRepo,
    TaskRepo,
    TeamMemberRepo,
    TeamRepo,
    WakeRepo,
    WorkforcePlanRepo,
)


class _LedgerConnection(sqlite3.Connection):
    """A ``sqlite3.Connection`` that lets the facade batch repo writes into one transaction.

    Repos call ``execute``/``commit``/``rollback`` exactly as on a real connection. Outside a
    transaction each repo write is its own unit (``commit`` passes through). Inside
    :meth:`LedgerCore.transaction` intermediate commits are *deferred* — the facade commits once on
    success or rolls back on error — so cross-aggregate operations land atomically (spec 01 Cluster F).
    """

    _defer_depth: int = 0  # >0 while a facade transaction is batching writes
    _tx_aborted: bool = False  # latched if any (even nested, caught) block raised

    def commit(self) -> None:
        if self._defer_depth == 0:
            super().commit()


@runtime_checkable
class Ledger(Protocol):
    """The durable store the scheduler reads and writes (spec 01) — the swappable seam.

    Implemented by :class:`SqliteLedger` and :class:`~chorus.ledger.postgres.PostgresLedger`
    (spec 12); the kernel depends on this shape, never on a concrete driver.
    """

    employees: EmployeeRepo
    goals: GoalRepo
    tasks: TaskRepo
    management_profiles: ManagementProfileRepo
    teams: TeamRepo
    team_members: TeamMemberRepo
    delegation_contracts: DelegationContractRepo
    decomposition_claims: DecompositionClaimRepo
    dependencies: DependencyRepo
    wakes: WakeRepo
    messages: MessageRepo
    approvals: ApprovalRepo
    decisions: DecisionRepo
    claims: ClaimRepo
    activity: ActivityRepo
    monitors: MonitorRepo
    recovery_actions: RecoveryActionRepo
    routines: RoutineRepo
    routine_revisions: RoutineRevisionRepo
    routine_triggers: RoutineTriggerRepo
    routine_runs: RoutineRunRepo
    runs: RunRepo
    dod: DodRepo
    artifacts: ArtifactRepo
    artifact_revisions: ArtifactRevisionRepo
    budget_policies: BudgetPolicyRepo
    budget_incidents: BudgetIncidentRepo
    cost_events: CostEventRepo
    workforce_plans: WorkforcePlanRepo
    staffing_requests: StaffingRequestRepo

    def schema_version(self) -> str | None: ...

    def transaction(self) -> AbstractContextManager[None]: ...

    def finalize_beat(
        self,
        *,
        task_id: str,
        run_id: str | None,
        dod_status: DodStatus,
        verdict: dict[str, object] | None = None,
    ) -> list[Wake]: ...

    def create_child(self, claim_id: str, child: Task) -> DecompositionClaim: ...

    def close(self) -> None: ...


class SqliteLedger(LedgerCore):
    """The file-backed default :class:`Ledger` (spec 01, spec 12).

    ``open`` connects, enables foreign keys, applies any pending migrations (the applied-set runner,
    spec 01 §schema-versioning), and wires one repo per aggregate onto the shared connection.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        if not isinstance(conn, _LedgerConnection):
            raise TypeError(
                "SqliteLedger requires a connection from SqliteLedger.open() "
                "(transaction batching depends on it); a plain sqlite3.Connection won't do"
            )
        self._sqlite_conn: _LedgerConnection = conn
        self._runner = MigrationRunner(MIGRATIONS)
        super().__init__(conn)

    @classmethod
    def open(cls, db_path: str) -> SqliteLedger:
        """Open (creating + migrating) the ledger at ``db_path`` (use ``":memory:"`` for tests)."""
        conn = sqlite3.connect(db_path, factory=_LedgerConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        ledger = cls(conn)
        ledger._runner.apply(conn)
        return ledger

    def schema_version(self) -> str | None:
        """The highest applied migration id — presentation only (spec 01 §schema-versioning)."""
        return self._runner.display_version(self._sqlite_conn)

    def close(self) -> None:
        self._sqlite_conn.close()


__all__ = [
    "Ledger",
    "SqliteLedger",
]
