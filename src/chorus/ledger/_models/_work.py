"""Work-DAG row models — Task, its dependency edges, and decomposition claims (Cluster A)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chorus.ledger._models._enums import (
    DecompositionStatus,
    ExecutionMode,
    OriginKind,
    TaskPriority,
    TaskStatus,
)


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
    execution_mode: ExecutionMode = ExecutionMode.DELIVERY
    team_id: str | None = None
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
    # §4 trust posture — the preset *value* (kept a plain str so the model stays trust-module-free);
    # ``None`` lets the TrustPolicy derive it. ``trust_boundary`` is the JSON {secret_ref_allowlist}.
    trust_preset: str | None = None
    trust_boundary: dict[str, object] | None = None


@dataclass(frozen=True)
class TaskDependency:
    """The real DAG edge — ``A depends_on B`` (spec 01 Cluster A ``task_dependency``)."""

    id: str
    task_id: str
    depends_on_id: str
    created_at: datetime | None = None


@dataclass(frozen=True)
class DecompositionClaim:
    """Exact-once fan-out — the manager-splits-work primitive (spec 01 Cluster A).

    The most important crash-safety object after the locks. The claim is durable *before* fan-out
    starts; ``child_task_ids`` is the durable partial result accumulated one-per-tx while underway;
    the completed set is durable after. Re-reading the same accepted plan revision can't authorize a
    second child tree — the ``(source_task_id, accepted_plan_revision_id)`` pair is unique, so a
    retry resumes the same claim and reuses the children it already created.
    """

    id: str
    source_task_id: str
    accepted_plan_revision_id: str
    owner_run_id: str | None = None
    status: DecompositionStatus = DecompositionStatus.IN_FLIGHT
    request_fingerprint: str = ""
    requested_children: list[dict[str, object]] = field(default_factory=list)
    child_task_ids: list[str] = field(default_factory=list)
    completed_at: datetime | None = None
    created_at: datetime | None = None
