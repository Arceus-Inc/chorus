"""The core ledger row models (spec 01 Clusters A, C, D).

Every row is durable; the scheduler holds no state not in these tables (B2.2).
These are the dream-native, single-workforce slim of Paperclip's 86-table model.
The frozen dataclasses below carry the load-bearing columns each subsystem
queries; the full SQL schema (partial-unique crash-safety indexes, the two-lock
contract, the budget/artifact clusters) lives in spec 01 and ``_ledger.py``'s
DDL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chorus.outcomes import Verifier


class TaskStatus(StrEnum):
    """The universal work-unit lifecycle (spec 01 Cluster A)."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"


class TaskPriority(StrEnum):
    """Dispatch priority band (spec 03 §3 sort key)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OriginKind(StrEnum):
    """What spawned a task — keys the partial-unique exact-once indexes (spec 01)."""

    MANUAL = "manual"
    ROUTINE_EXECUTION = "routine_execution"
    DECOMPOSITION = "decomposition"
    STRANDED_RECOVERY = "stranded_recovery"
    STALE_RUN_EVAL = "stale_run_eval"
    PRODUCTIVITY_REVIEW = "productivity_review"


class RunStatus(StrEnum):
    """One beat's lifecycle (spec 01 Cluster C ``run``)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class GoalLevel(StrEnum):
    """The alignment tree levels (spec 01 Cluster D ``goal``)."""

    COMPANY = "company"
    TEAM = "team"
    EMPLOYEE = "employee"
    TASK = "task"


@dataclass(frozen=True)
class Task:
    """The universal work unit — the ExecPlan made durable (spec 01 Cluster A).

    Hard invariants (spec 01): single assignee (``assignee_employee_id`` XOR
    ``assignee_user_id``); ``in_progress`` requires an assignee + a live path;
    every task traces to a goal; the two locks are distinct
    (``checkout_run_id`` = who owns the right to execute, ``execution_run_id`` =
    which run is live), enforced on dream's board and mirrored here for queries.
    """

    id: str
    intent: str
    status: TaskStatus = TaskStatus.BACKLOG
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_employee_id: str | None = None
    assignee_user_id: str | None = None
    goal_id: str | None = None
    parent_id: str | None = None
    dod: Verifier | None = None
    depth: int = 0
    request_depth: int = 0
    origin_kind: OriginKind = OriginKind.MANUAL
    origin_id: str | None = None
    origin_fingerprint: str = "default"
    checkout_run_id: str | None = None
    execution_run_id: str | None = None
    created_by_employee_id: str | None = None
    created_by_user_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancelled_at: datetime | None = None


@dataclass(frozen=True)
class TaskDependency:
    """The real DAG edge — ``A depends_on B`` (spec 01 Cluster A ``task_dependency``)."""

    id: str
    task_id: str
    depends_on_id: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class Run:
    """One beat — one ``dream.run_task`` invocation, kept THIN (spec 01 Cluster C ``run``)."""

    id: str
    employee_id: str
    task_id: str
    wake_id: str | None = None
    status: RunStatus = RunStatus.QUEUED
    lease_expires_at: datetime | None = None
    liveness_state: str | None = None
    continuation_attempt: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: dict[str, object] = field(default_factory=dict)
    usage: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class Goal:
    """A node in the alignment tree (spec 01 Cluster D ``goal``).

    horizon seam: this tree is the local mirror horizon will later own; until
    then goals are seeded flat at intake (spec 01 Cluster D note).
    """

    id: str
    title: str
    level: GoalLevel = GoalLevel.COMPANY
    status: str = "active"
    parent_id: str | None = None
    owner_employee_id: str | None = None


__all__ = [
    "Goal",
    "GoalLevel",
    "OriginKind",
    "Run",
    "RunStatus",
    "Task",
    "TaskDependency",
    "TaskPriority",
    "TaskStatus",
]
