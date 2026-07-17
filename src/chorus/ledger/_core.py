"""The driver-shared ledger core: repo composition + the cross-aggregate atomic operations.

Every ``Ledger`` driver (SQLite, Postgres) wires the same repos onto its connection and shares the
same ``transaction()`` batching and cross-aggregate methods (``finalize_beat``, ``create_child``).
Only ``open`` (connection setup, type adaptation) and the migration DDL are dialect-specific — the
spec 12 §3 discipline, in code.

The batching contract: the driver's connection object carries ``_defer_depth``/``_tx_aborted`` and
defers ``commit()`` while ``_defer_depth > 0``. ``transaction()`` manipulates only that surface, so
one implementation serves every driver.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol

from chorus.ids import mint_id
from chorus.ledger._models import (
    DecompositionClaim,
    DecompositionStatus,
    DodStatus,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)
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
from chorus.ledger.repos._base import LedgerConnection


class BatchingConnection(LedgerConnection, Protocol):
    """A driver connection that supports the facade's commit-deferral batching."""

    _defer_depth: int
    _tx_aborted: bool


def _wake_id() -> str:
    return mint_id()


class LedgerCore:
    """Repo wiring + the atomic cross-aggregate operations, shared by every driver."""

    def __init__(self, conn: BatchingConnection) -> None:
        self._conn: BatchingConnection = conn
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


__all__ = ["BatchingConnection", "LedgerCore"]
