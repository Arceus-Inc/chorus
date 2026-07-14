"""The ledger facade (spec 01) — opens the store, applies migrations, composes the repos.

``SqliteLedger`` is the durable source of truth for "what work exists and where it is." The kernel
reads/writes only through the per-aggregate repos it exposes (B2.2); every transition is a durable
write. The same repo code runs on Postgres later behind the same ``Ledger`` shape (spec 12) — only
``open`` (connection setup) and the migration DDL are dialect-specific.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Protocol, runtime_checkable

from chorus.ids import mint_id
from chorus.ledger._migrations import MigrationRunner
from chorus.ledger._models import (
    DecompositionClaim,
    DecompositionStatus,
    DodStatus,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
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


def _wake_id() -> str:
    return mint_id("wake")


class _LedgerConnection(sqlite3.Connection):
    """A ``sqlite3.Connection`` that lets the facade batch repo writes into one transaction.

    Repos call ``execute``/``commit``/``rollback`` exactly as on a real connection. Outside a
    transaction each repo write is its own unit (``commit`` passes through). Inside
    :meth:`SqliteLedger.transaction` intermediate commits are *deferred* — the facade commits once on
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

    Implemented by :class:`SqliteLedger` now and a Postgres-backed ledger in Arceus (spec 12);
    the kernel depends on this shape, never on a concrete driver.
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


class SqliteLedger:
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
        self._conn: _LedgerConnection = conn
        self._runner = MigrationRunner(MIGRATIONS)
        self.employees = EmployeeRepo(conn)
        self.goals = GoalRepo(conn)
        self.tasks = TaskRepo(conn)
        self.management_profiles = ManagementProfileRepo(conn)
        self.teams = TeamRepo(conn)
        self.team_members = TeamMemberRepo(conn)
        self.delegation_contracts = DelegationContractRepo(conn)
        self.decomposition_claims = DecompositionClaimRepo(conn)
        self.dependencies = DependencyRepo(conn)
        self.wakes = WakeRepo(conn)
        self.messages = MessageRepo(conn)
        self.approvals = ApprovalRepo(conn)
        self.decisions = DecisionRepo(conn)
        self.claims = ClaimRepo(conn)
        self.activity = ActivityRepo(conn)
        self.monitors = MonitorRepo(conn)
        self.recovery_actions = RecoveryActionRepo(conn)
        self.routines = RoutineRepo(conn)
        self.routine_revisions = RoutineRevisionRepo(conn)
        self.routine_triggers = RoutineTriggerRepo(conn)
        self.routine_runs = RoutineRunRepo(conn)
        self.runs = RunRepo(conn)
        self.dod = DodRepo(conn)
        self.artifacts = ArtifactRepo(conn)
        self.artifact_revisions = ArtifactRevisionRepo(conn)
        self.budget_policies = BudgetPolicyRepo(conn)
        self.budget_incidents = BudgetIncidentRepo(conn)
        self.cost_events = CostEventRepo(conn)
        self.workforce_plans = WorkforcePlanRepo(conn)
        self.staffing_requests = StaffingRequestRepo(conn)

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
        return self._runner.display_version(self._conn)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Batch every repo write in the block into one transaction (atomic commit / rollback).

        Repo methods defer their per-call commits while this is active; the outermost block commits
        once on success or rolls back if *any* block — including a nested one whose exception was
        caught by surrounding code — raised. Re-entrant: nested blocks are one transaction.
        """
        conn = self._conn
        conn._defer_depth += 1
        try:
            yield
        except BaseException:
            conn._tx_aborted = True  # latch so the outermost block can't commit partial writes
            raise
        finally:
            conn._defer_depth -= 1
            if conn._defer_depth == 0:
                aborted = conn._tx_aborted
                conn._tx_aborted = False
                if aborted:
                    conn.rollback()
                else:
                    conn.commit()  # depth back to 0 -> a real commit

    def finalize_beat(
        self,
        *,
        task_id: str,
        run_id: str | None,
        dod_status: DodStatus,
        verdict: dict[str, object] | None = None,
    ) -> list[Wake]:
        """Apply a beat's verdict atomically (spec 01 Cluster F, spec 03 ``fire_downstream_wakes``).

        In one transaction: record the ``dod`` verdict (if the task has a dod row), and — when the
        verdict is ``passed`` — derive ``task.status='done'`` (+ ``completed_at``) and enqueue the
        downstream wakes that let the *next* beat pick up the now-unblocked work (``deps_resolved``
        for newly-unblocked dependents, ``children_done`` for a parent whose last child just landed).
        A non-passed verdict only records the dod result and leaves the task for rework. Returns the
        wakes enqueued.
        """
        with self.transaction():
            dod = self.dod.get_for_task(task_id)
            if dod is not None:
                self.dod.record_verdict(dod.id, dod_status, verdict=verdict, run_id=run_id)
            if dod_status is not DodStatus.PASSED:
                return []
            self.tasks.set_status(task_id, TaskStatus.DONE)
            return self._fire_downstream_wakes(task_id)

    def create_child(self, claim_id: str, child: Task) -> DecompositionClaim:
        """Create a decomposition child + record it on the claim in one transaction (spec 02 §4).

        The child ``task`` insert and the ``child_task_ids`` append commit together (or neither), so a
        crash mid-fan-out never leaves a task the claim doesn't know about. **Idempotent on retry**:
        if the child is already recorded on the claim the existing claim is returned unchanged (no
        duplicate-insert), so a resumed fan-out reuses already-created children (spec 02 §4). A sealed
        (non-``in_flight``) claim rejects the child before any task is inserted.
        """
        with self.transaction():
            claim = self.decomposition_claims.get(claim_id)
            if claim is None:
                raise KeyError(claim_id)
            if claim.status is not DecompositionStatus.IN_FLIGHT:
                raise ValueError(f"claim {claim_id} is {claim.status.value}, not in_flight")
            if child.id in claim.child_task_ids:
                return claim  # already created on a prior attempt — idempotent no-op
            self.tasks.submit(child)
            return self.decomposition_claims.add_child(claim_id, child.id)

    def _fire_downstream_wakes(self, task_id: str) -> list[Wake]:
        """Enqueue ``deps_resolved`` / ``children_done`` wakes for a just-completed task."""
        fired: list[Wake] = []
        task = self.tasks.get(task_id)
        for dependent_id in self.dependencies.newly_unblocked_dependents(task_id):
            dependent = self.tasks.get(dependent_id)
            if dependent is not None and dependent.assignee_employee_id is not None:
                fired.append(
                    self.wakes.enqueue(
                        Wake(
                            id=_wake_id(),
                            employee_id=dependent.assignee_employee_id,
                            reason=WakeReason.DEPS_RESOLVED,
                            payload={"task_id": dependent_id},
                        )
                    )
                )
        if (
            task is not None
            and task.parent_id is not None
            and self.tasks.all_children_terminal(task.parent_id)
        ):
            parent = self.tasks.get(task.parent_id)
            if parent is not None and parent.assignee_employee_id is not None:
                fired.append(
                    self.wakes.enqueue(
                        Wake(
                            id=_wake_id(),
                            employee_id=parent.assignee_employee_id,
                            reason=WakeReason.CHILDREN_DONE,
                            payload={"task_id": task.parent_id},
                        )
                    )
                )
        return fired

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "Ledger",
    "SqliteLedger",
]
