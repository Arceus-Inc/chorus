"""The inspector — a pure read model over the ledger + event log (spec 08 §3).

Holds no state. Surfaces (Paperclip's layered liveness UI, adapted): the live
beat surface (from the ``run.*`` stream), the liveness vocabulary (straight from
``run.evaluated``), recovery cards (one per open ``recovery_action``), and the
blocked inbox (every stalled task, ranked). The CLI ``chorus inspect`` and (in
Arceus) the web board are both views over this projection.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import ActivityVerb, RunStatus, TaskStatus
from chorus.lifecycle import classify
from chorus.observability._views import (
    DelegationContractView,
    EmployeeView,
    IncidentView,
    ManagementProfileView,
    OrgObservabilityReport,
    RoutineRunView,
    RoutineTriggerView,
    RoutineView,
    RunView,
    ScrumChildView,
    ScrumPacketView,
    TaskView,
    TeamView,
    WorkforceStatus,
)

if False:  # pragma: no cover - typing only without runtime import cost
    from chorus.ledger import SqliteLedger
    from chorus.ledger._models import Routine, Run, Task

_RECENT_RUNS = 5  # how many of a routine's most-recent firings the read model surfaces
_TERMINAL = frozenset({TaskStatus.DONE, TaskStatus.CANCELLED, TaskStatus.REJECTED})


def _utc_now() -> datetime:
    return datetime.now(UTC)


@runtime_checkable
class Inspector(Protocol):
    """The read-model contract (spec 09 §4) — swappable behind the facade."""

    def status(self) -> WorkforceStatus:
        """The company at a glance — employees, open tasks, runs, incidents."""
        ...

    def task(self, task_id: str) -> TaskView:
        """One task, resolved (names + liveness + blockers)."""
        ...

    def stuck(self) -> list[TaskView]:
        """The blocked inbox — non-terminal tasks with no action-path primitive (spec 08 §2)."""
        ...

    def scrum_packet(self, parent_task_id: str) -> ScrumPacketView:
        """Manager packet rollup for one delegated parent task."""
        ...

    def org_report(self) -> OrgObservabilityReport:
        """Combined manager + leaf observability rollup."""
        ...

    def teams(self) -> list[TeamView]:
        """Every durable Team, including archived history."""
        ...

    def delegation_contracts(self) -> list[DelegationContractView]:
        """Every delegation contract, including completed history."""
        ...

    def management_profiles(self) -> list[ManagementProfileView]:
        """Every current management profile, including inactive grants."""
        ...

    def routine(self, routine_id: str) -> RoutineView:
        """One routine, resolved: definition + triggers + recent firings (spec 13 §7)."""
        ...

    def list_routines(self, *, employee_id: str | None = None) -> list[RoutineView]:
        """Every routine (any status), optionally scoped to one employee (spec 13 §7)."""
        ...


class LedgerInspector:
    """The default :class:`Inspector` over the SQLite ledger + event log (spec 08 §3)."""

    def __init__(self, ledger: SqliteLedger, *, clock: Callable[[], datetime] = _utc_now) -> None:
        self._ledger = ledger
        self._clock = clock  # liveness compares run leases to ``now`` — injected for determinism

    def status(self) -> WorkforceStatus:
        now = self._clock()
        tasks = self._ledger.tasks.all()
        employees = tuple(
            EmployeeView(
                id=employee.id, name=employee.name, role=employee.role, status=employee.status.value
            )
            for employee in self._ledger.employees.list()
        )
        running = sum(
            1
            for task in tasks
            for run in self._ledger.runs.for_task(task.id)
            if run.status is RunStatus.RUNNING
        )
        blocked = tuple(self._task_view(task, now) for task in tasks if self._is_stuck(task, now))
        return WorkforceStatus(
            employees=employees,
            open_tasks=sum(1 for task in tasks if task.status not in _TERMINAL),
            running_beats=running,
            blocked=blocked,
            open_incidents=self._open_incidents(),
        )

    def task(self, task_id: str) -> TaskView:
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        return self._task_view(task, self._clock())

    def stuck(self) -> list[TaskView]:
        now = self._clock()
        return [
            self._task_view(task, now)
            for task in self._ledger.tasks.all()
            if self._is_stuck(task, now)
        ]

    def _is_stuck(self, task: Task, now: datetime) -> bool:
        """Non-terminal and stalled — no action-path primitive (spec 08 §2), per ``classify``."""
        return task.status not in _TERMINAL and classify(task, self._ledger, now=now).stalled

    def _task_view(self, task: Task, now: datetime) -> TaskView:
        assignee = None
        if task.assignee_employee_id is not None:
            employee = self._ledger.employees.get(task.assignee_employee_id)
            assignee = employee.name if employee is not None else task.assignee_employee_id
        runs = self._ledger.runs.for_task(task.id)
        return TaskView(
            id=task.id,
            intent=task.intent,
            status=task.status,
            priority=task.priority.value,
            assignee=assignee,
            goal_id=task.goal_id,
            depth=task.depth,
            request_depth=task.request_depth,
            dod=self._ledger.dod.verifier_for_task(task.id),
            latest_run=self._run_view(runs[-1]) if runs else None,
            liveness=classify(task, self._ledger, now=now).health.value,
            blockers=tuple(self._ledger.dependencies.unresolved_blockers(task.id)),
        )

    @staticmethod
    def _run_view(run: Run) -> RunView:
        return RunView(
            id=run.id,
            task_id=run.task_id,
            employee_id=run.employee_id,
            status=run.status.value,
            liveness_state=run.liveness_state,
            started_at=run.started_at,
            finished_at=run.finished_at,
        )

    def _open_incidents(self) -> tuple[IncidentView, ...]:
        """The decisions a human owes: open budget incidents + open recovery actions (spec 08 §3)."""
        incidents = [
            IncidentView(
                id=incident.id,
                kind="budget",
                subject_id=incident.policy_id,
                cause=incident.threshold_type.value,
                next_action="raise the budget to resume",
            )
            for policy in self._ledger.budget_policies.all()
            for incident in self._ledger.budget_incidents.open_for_policy(policy.id)
        ]
        incidents.extend(
            IncidentView(
                id=action.id,
                kind="recovery",
                subject_id=action.source_task_id,
                cause=action.kind.value,
                owner=action.owner_employee_id,
            )
            for action in self._ledger.recovery_actions.all_open()
        )
        return tuple(incidents)

    def scrum_packet(self, parent_task_id: str) -> ScrumPacketView:
        parent = self._ledger.tasks.get(parent_task_id)
        if parent is None:
            raise KeyError(parent_task_id)
        packet = IntegrateContextPacket.build(
            self._ledger, parent_task_id=parent_task_id, audit=False
        )
        assignment_count = 0
        reassignment_count = 0
        for child in packet.children:
            for activity in self._ledger.activity.by_subject("task", child.task_id):
                if activity.verb is ActivityVerb.ASSIGNED:
                    assignment_count += 1
                    if activity.payload.get("reassigned") is True:
                        reassignment_count += 1
        parent_edges = len(self._ledger.dependencies.blockers(parent_task_id))
        child_edges = sum(
            len(self._ledger.dependencies.blockers(child.task_id)) for child in packet.children
        )
        completed = sum(1 for child in packet.children if child.status in _TERMINAL_STATUS_VALUES)
        blocked = sum(1 for child in packet.children if child.blockers)
        total = len(packet.children)
        return ScrumPacketView(
            parent_task_id=parent.id,
            parent_intent=parent.intent,
            manager_id=parent.assignee_employee_id,
            iteration=packet.iteration,
            recommended_action=packet.recommended_action,
            child_count=total,
            completed_children=completed,
            blocked_children=blocked,
            dependency_edges=parent_edges + child_edges,
            assignment_count=assignment_count,
            reassignments=reassignment_count,
            completion_rate=_rate(completed, total),
            children=tuple(
                ScrumChildView(
                    task_id=child.task_id,
                    label=child.label,
                    assignee=child.assignee,
                    assignee_role=child.assignee_role,
                    status=child.status,
                    blockers=child.blockers,
                    dod_status=child.dod_status,
                    latest_run_status=child.latest_run_status,
                    latest_run_summary=child.latest_run_summary,
                    artifact_type=child.artifact_type,
                )
                for child in packet.children
            ),
        )

    def org_report(self) -> OrgObservabilityReport:
        employees = self._ledger.employees.list()
        manager_ids = {
            employee.reports_to for employee in employees if employee.reports_to is not None
        }
        tasks = self._ledger.tasks.all()
        activities = self._ledger.activity.all()
        assignment_activities = [a for a in activities if a.verb is ActivityVerb.ASSIGNED]
        packets = tuple(
            self.scrum_packet(task.id) for task in tasks if self._ledger.tasks.has_children(task.id)
        )
        runs = [run for task in tasks for run in self._ledger.runs.for_task(task.id)]
        done = sum(1 for task in tasks if task.status is TaskStatus.DONE)
        return OrgObservabilityReport(
            employees=len(employees),
            managers=len(manager_ids),
            leaves=len(employees) - len(manager_ids),
            tasks_total=len(tasks),
            tasks_done=done,
            tasks_blocked=sum(1 for task in tasks if task.status is TaskStatus.BLOCKED),
            running_beats=sum(1 for run in runs if run.status is RunStatus.RUNNING),
            failed_runs=sum(1 for run in runs if run.status in _FAILED_RUN_STATUSES),
            completion_rate=_rate(done, len(tasks)),
            decomposition_count=sum(1 for a in activities if a.verb is ActivityVerb.DECOMPOSED),
            assignment_count=len(assignment_activities),
            reassignment_count=sum(
                1 for a in assignment_activities if a.payload.get("reassigned") is True
            ),
            dependency_edges=sum(
                len(self._ledger.dependencies.blockers(task.id)) for task in tasks
            ),
            manager_packets=packets,
        )

    def teams(self) -> list[TeamView]:
        return [
            TeamView(
                id=team.id,
                name=team.name,
                lead_employee_id=team.lead_employee_id,
                status=team.status,
                policy_version=team.policy_version,
                created_by=team.created_by,
                goal_id=team.goal_id,
                parent_team_id=team.parent_team_id,
                member_employee_ids=tuple(
                    member.employee_id for member in self._ledger.team_members.members_of(team.id)
                ),
            )
            for team in self._ledger.teams.list()
        ]

    def delegation_contracts(self) -> list[DelegationContractView]:
        return [
            DelegationContractView(
                task_id=contract.task_id,
                team_id=contract.team_id,
                lead_employee_id=contract.lead_employee_id,
                management_profile_version=contract.management_profile_version,
                objective_rubric=contract.objective_rubric,
                status=contract.status,
                parent_contract_task_id=contract.parent_contract_task_id,
                can_subdelegate=contract.can_subdelegate,
                max_depth=contract.max_depth,
                max_team_size=contract.max_team_size,
                spend_limit_cents=contract.spend_limit_cents,
                accepted_run_id=contract.accepted_run_id,
            )
            for contract in self._ledger.delegation_contracts.list()
        ]

    def management_profiles(self) -> list[ManagementProfileView]:
        return [
            ManagementProfileView(
                employee_id=profile.employee_id,
                granted_by_user_id=profile.granted_by_user_id,
                active=profile.active,
                can_lead=profile.can_lead,
                can_subdelegate=profile.can_subdelegate,
                max_delegation_depth=profile.max_delegation_depth,
                max_team_size=profile.max_team_size,
                allowed_professions=profile.allowed_professions,
                spend_limit_cents=profile.spend_limit_cents,
                version=profile.version,
            )
            for profile in self._ledger.management_profiles.list()
        ]

    def routine(self, routine_id: str) -> RoutineView:
        routine = self._ledger.routines.get(routine_id)
        if routine is None:
            raise KeyError(routine_id)
        return self._routine_view(routine)

    def list_routines(self, *, employee_id: str | None = None) -> list[RoutineView]:
        return [
            self._routine_view(routine)
            for routine in self._ledger.routines.list(employee_id=employee_id)
        ]

    def _routine_view(self, routine: Routine) -> RoutineView:
        triggers = tuple(
            RoutineTriggerView(
                id=trigger.id,
                kind=trigger.kind,
                cron_expression=trigger.cron_expression,
                timezone=trigger.timezone,
                next_run_at=trigger.next_run_at,
                last_fired_at=trigger.last_fired_at,
            )
            for trigger in self._ledger.routine_triggers.by_routine(routine.id)
        )
        recent = self._ledger.routine_runs.by_routine(routine.id)[-_RECENT_RUNS:]
        runs = tuple(
            RoutineRunView(
                id=run.id,
                status=run.status,
                linked_task_id=run.linked_task_id,
                coalesced_into_run_id=run.coalesced_into_run_id,
            )
            for run in reversed(recent)  # newest firing first
        )
        return RoutineView(
            id=routine.id,
            employee_id=routine.employee_id,
            intent_template=routine.intent_template,
            target=routine.target,
            concurrency_policy=routine.concurrency_policy,
            catch_up_policy=routine.catch_up_policy,
            status=routine.status,
            latest_revision_no=routine.latest_revision_no,
            triggers=triggers,
            recent_runs=runs,
        )


_TERMINAL_STATUS_VALUES = {
    TaskStatus.DONE.value,
    TaskStatus.CANCELLED.value,
    TaskStatus.REJECTED.value,
}
_FAILED_RUN_STATUSES = {RunStatus.FAILED, RunStatus.TIMED_OUT, RunStatus.CANCELLED}


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


__all__ = [
    "Inspector",
    "LedgerInspector",
]
