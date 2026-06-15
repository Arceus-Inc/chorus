"""The core ledger row models (spec 01 Clusters A, C, D, F).

Every row is durable; the scheduler holds no state not in these tables (B2.2).
These are the dream-native, single-workforce slim of Paperclip's 86-table model.
The frozen dataclasses below are the typed row shapes the repos map to/from; the
SQL schema (partial-unique crash-safety indexes, the two-lock contract) lives in
``migrations/`` and is applied by the :class:`SqliteLedger` facade.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


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


class DodStatus(StrEnum):
    """The verification verdict on a :class:`Dod` (spec 01 Cluster F)."""

    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"


class ArtifactType(StrEnum):
    """What kind of landed outcome an :class:`Artifact` is (spec 01 Cluster F)."""

    PR = "pr"
    DOC = "doc"
    FINDING = "finding"
    ARTIFACT = "artifact"
    WORKSPACE_FILE = "workspace_file"


@dataclass(frozen=True)
class Task:
    """The universal work unit — the ExecPlan made durable (spec 01 Cluster A).

    Hard invariants (spec 01): single assignee (``assignee_employee_id`` XOR
    ``assignee_user_id``); ``in_progress`` requires an assignee + a live path;
    every task traces to a goal; the two locks are distinct
    (``checkout_run_id`` = who owns the right to execute, ``execution_run_id`` =
    which run is live) — authoritative columns in *this* ledger, set by the atomic
    checkout CAS (spec 01 invariant 4); dream's board is swarm-only. The DoD is a
    1:1 ``dod`` row, not a column (Cluster F).
    """

    id: str
    intent: str
    status: TaskStatus = TaskStatus.BACKLOG
    priority: TaskPriority = TaskPriority.MEDIUM
    assignee_employee_id: str | None = None
    assignee_user_id: str | None = None
    goal_id: str | None = None
    parent_id: str | None = None
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


@dataclass(frozen=True)
class Dod:
    """Definition-of-done + verification record, 1:1 with a task (spec 01 Cluster F).

    The ``dod`` row is the authoritative verdict: ``task.status`` is derived from
    ``status`` (``done`` iff ``passed``); ``run.outcome`` is the raw input it is
    computed from (spec 01 Cluster F invariant).
    """

    id: str
    task_id: str
    kind: str
    spec: dict[str, object] = field(default_factory=dict)
    artifact_class: str | None = None
    revision: int = 1
    status: DodStatus = DodStatus.PENDING
    verdict: dict[str, object] | None = None
    verified_by_run_id: str | None = None


@dataclass(frozen=True)
class Artifact:
    """A landed outcome — a PR, doc, or finding (spec 01 Cluster F)."""

    id: str
    task_id: str
    type: ArtifactType
    provider: str | None = None
    external_id: str | None = None
    url: str | None = None
    review_state: str | None = None
    health_status: str | None = None
    is_primary: bool = False
    resource_ref: dict[str, object] | None = None


__all__ = [
    "Artifact",
    "ArtifactType",
    "Dod",
    "DodStatus",
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
