"""The inspector read-model projections (spec 08 §3, spec 10 §1).

The facade's inspection methods return these frozen dataclasses — typed read
*projections* over the ledger + event log, not the rows themselves. They resolve
names and derive liveness so a caller never re-implements the queries (spec 10
§1). "Working vs stuck" is answered structurally from durable state, not from
byte-silence timing (spec 08 §2).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chorus.ledger import DelegationContractStatus, TaskStatus, TeamStatus
from chorus.ledger._models import (
    Activity,
    Artifact,
    ArtifactRevision,
    CostEvent,
    Dod,
    Goal,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRunStatus,
    RoutineStatus,
    RoutineTarget,
    Run,
    Task,
    TriggerKind,
)
from chorus.outcomes import Verifier


@dataclass(frozen=True)
class RunView:
    """One beat, resolved for reading (the live-beat surface, spec 08 §3)."""

    id: str
    task_id: str
    employee_id: str
    status: str
    principal_kind: str = "employee"
    principal_id: str | None = None
    liveness_state: str | None = None
    score: float | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass(frozen=True)
class EmployeeView:
    """One employee at a glance (spec 08 §2 working/stuck signals)."""

    id: str
    name: str
    role: str
    status: str
    last_beat_at: datetime | None = None
    spent_monthly_cents: int = 0


@dataclass(frozen=True)
class IncidentView:
    """A budget or recovery incident a human owes a decision on (spec 08 §3)."""

    id: str
    kind: str  # 'budget' | 'recovery'
    subject_id: str
    cause: str
    owner: str | None = None
    next_action: str = ""


@dataclass(frozen=True)
class TaskView:
    """One task, resolved for reading (spec 10 §1).

    ``liveness`` is derived (``'healthy'`` | ``'stalled'``, spec 02 §3);
    ``blockers`` are the unresolved ``task_dependency`` leaves — a task is stuck
    iff it is non-terminal and has no action-path primitive (spec 08 §2), a
    query, not a heuristic.
    """

    id: str
    intent: str
    status: TaskStatus
    priority: str
    assignee: str | None = None
    goal_id: str | None = None
    depth: int = 0
    request_depth: int = 0
    dod: Verifier | None = None
    latest_run: RunView | None = None
    liveness: str = "healthy"
    blockers: tuple[str, ...] = ()


@dataclass(frozen=True)
class TaskThreadRunView:
    """One run in a task thread, with matching and malformed spend rows separated."""

    run: Run
    cost_events: tuple[CostEvent, ...] = ()
    mismatched_cost_events: tuple[CostEvent, ...] = ()


@dataclass(frozen=True)
class TaskThreadArtifactView:
    """One task artifact, plus its optional revision history and audit trail."""

    artifact: Artifact
    revisions: tuple[ArtifactRevision, ...] = ()
    activity: tuple[Activity, ...] = ()


@dataclass(frozen=True)
class TaskThreadTaskView:
    """One task in a subtree, with its directly attached ledger rows."""

    task: Task
    runs: tuple[TaskThreadRunView, ...] = ()
    task_only_cost_events: tuple[CostEvent, ...] = ()
    dod: Dod | None = None
    artifacts: tuple[TaskThreadArtifactView, ...] = ()
    activity: tuple[Activity, ...] = ()


@dataclass(frozen=True)
class TaskThreadView:
    """A task-centric subtree projection rooted at one requested task."""

    goal: Goal | None = None
    tasks: tuple[TaskThreadTaskView, ...] = ()


@dataclass(frozen=True)
class WorkforceStatus:
    """The company at a glance (spec 08, spec 10 §1)."""

    employees: tuple[EmployeeView, ...] = ()
    open_tasks: int = 0
    running_beats: int = 0
    blocked: tuple[TaskView, ...] = field(default_factory=tuple)
    open_incidents: tuple[IncidentView, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TeamView:
    """A durable Team with its current responsibility membership."""

    id: str
    name: str
    lead_employee_id: str
    status: TeamStatus
    policy_version: int
    created_by: str
    goal_id: str | None = None
    parent_team_id: str | None = None
    member_employee_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DelegationContractView:
    """Pinned delegation authority and its current lifecycle state."""

    task_id: str
    team_id: str
    lead_employee_id: str
    management_profile_version: int
    objective_rubric: str
    status: DelegationContractStatus
    parent_contract_task_id: str | None = None
    can_subdelegate: bool = False
    max_depth: int = 0
    max_team_size: int = 1
    max_direct_children: int | None = None
    spend_limit_cents: int | None = None
    accepted_run_id: str | None = None


@dataclass(frozen=True)
class ManagementProfileView:
    """Current bounded human-granted management authority for one specialist."""

    employee_id: str
    granted_by_user_id: str
    active: bool
    can_lead: bool
    can_subdelegate: bool
    max_delegation_depth: int
    max_team_size: int
    allowed_professions: tuple[str, ...]
    spend_limit_cents: int | None
    version: int


@dataclass(frozen=True)
class ScrumChildView:
    """One child row in a manager observability packet."""

    task_id: str
    label: str
    assignee: str | None
    assignee_role: str | None
    status: str
    blockers: tuple[str, ...] = ()
    dod_status: str | None = None
    latest_run_status: str | None = None
    latest_run_summary: str | None = None
    artifact_type: str | None = None


@dataclass(frozen=True)
class ScrumPacketView:
    """A manager-level packet rollup: child outcomes, routing churn, and dependency pressure."""

    parent_task_id: str
    parent_intent: str
    manager_id: str | None
    iteration: int
    recommended_action: str
    child_count: int
    completed_children: int
    blocked_children: int
    dependency_edges: int
    assignment_count: int
    reassignments: int
    completion_rate: float
    children: tuple[ScrumChildView, ...] = ()


@dataclass(frozen=True)
class OrgObservabilityReport:
    """Combined manager + leaf rollup for informed allocation decisions."""

    employees: int
    managers: int
    leaves: int
    tasks_total: int
    tasks_done: int
    tasks_blocked: int
    running_beats: int
    failed_runs: int
    completion_rate: float
    decomposition_count: int
    assignment_count: int
    reassignment_count: int
    dependency_edges: int
    manager_packets: tuple[ScrumPacketView, ...] = ()


@dataclass(frozen=True)
class RoutineTriggerView:
    """One routine trigger, resolved for reading (spec 13 §7 — the clock behind a routine)."""

    id: str
    kind: TriggerKind
    cron_expression: str | None
    timezone: str
    next_run_at: datetime | None
    last_fired_at: datetime | None


@dataclass(frozen=True)
class RoutineRunView:
    """One firing, resolved for reading — so a coalesced/suppressed firing is observable (spec 13 §7)."""

    id: str
    status: RoutineRunStatus
    linked_task_id: str | None
    coalesced_into_run_id: str | None


@dataclass(frozen=True)
class RoutineView:
    """A routine resolved for reading: its definition, its triggers, and recent firings (spec 13 §7).

    The caller-facing shape of a routine — the persistence splits it across ``routine`` /
    ``routine_trigger`` / ``routine_run``; this fuses them so a consumer never re-joins the tables.
    """

    id: str
    employee_id: str
    intent_template: str
    target: RoutineTarget
    concurrency_policy: RoutineConcurrency
    catch_up_policy: RoutineCatchUp
    status: RoutineStatus
    latest_revision_no: int = 1
    triggers: tuple[RoutineTriggerView, ...] = ()
    recent_runs: tuple[RoutineRunView, ...] = ()


__all__ = [
    "DelegationContractView",
    "EmployeeView",
    "IncidentView",
    "ManagementProfileView",
    "OrgObservabilityReport",
    "RoutineRunView",
    "RoutineTriggerView",
    "RoutineView",
    "RunView",
    "ScrumChildView",
    "ScrumPacketView",
    "TaskThreadArtifactView",
    "TaskThreadRunView",
    "TaskThreadTaskView",
    "TaskThreadView",
    "TaskView",
    "TeamView",
    "WorkforceStatus",
]
