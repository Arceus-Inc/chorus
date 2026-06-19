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

from chorus.ledger import TaskStatus
from chorus.outcomes import Verifier


@dataclass(frozen=True)
class RunView:
    """One beat, resolved for reading (the live-beat surface, spec 08 §3)."""

    id: str
    task_id: str
    employee_id: str
    status: str
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
class WorkforceStatus:
    """The company at a glance (spec 08, spec 10 §1)."""

    employees: tuple[EmployeeView, ...] = ()
    open_tasks: int = 0
    running_beats: int = 0
    blocked: tuple[TaskView, ...] = field(default_factory=tuple)
    open_incidents: tuple[IncidentView, ...] = field(default_factory=tuple)


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


__all__ = [
    "EmployeeView",
    "IncidentView",
    "OrgObservabilityReport",
    "RunView",
    "ScrumChildView",
    "ScrumPacketView",
    "TaskView",
    "WorkforceStatus",
]
