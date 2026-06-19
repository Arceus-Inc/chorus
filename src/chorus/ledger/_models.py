"""The core ledger row models (spec 01 Clusters A, C, D, F).

Every row is durable; the scheduler holds no state not in these tables (B2.2).
These are the dream-native, single-workforce slim of Paperclip's 86-table model.
The frozen dataclasses below are the typed row shapes the repos map to/from; the
SQL schema (partial-unique crash-safety indexes, the two-lock contract) lives in
``migrations/`` and is applied by the :class:`SqliteLedger` facade.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    """The universal work-unit lifecycle (spec 01 Cluster A)."""

    BACKLOG = "backlog"
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    BLOCKED = "blocked"
    DONE = "done"
    CANCELLED = "cancelled"
    REJECTED = "rejected"  # terminal: a reviewer blocked the deliverable (M3 load-bearing Reviewer)


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
    VERDICT = "verdict"


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


class DecompositionStatus(StrEnum):
    """A fan-out claim's lifecycle (spec 01 Cluster A ``decomposition_claim``)."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"


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


class RoutineTarget(StrEnum):
    """What a routine firing produces (spec 01 Cluster C ``routine``)."""

    SPAWN_TASK = "spawn_task"
    NEXT_BEAT = "next_beat"


class RoutineConcurrency(StrEnum):
    """How a routine handles an already-active prior firing (spec 01 Cluster C)."""

    SKIP_IF_ACTIVE = "skip_if_active"
    COALESCE = "coalesce"
    ALWAYS = "always"


class RoutineCatchUp(StrEnum):
    """How a routine treats missed windows (spec 01 Cluster C)."""

    SKIP_MISSED = "skip_missed"
    BACKFILL_ONE = "backfill_one"


class RoutineStatus(StrEnum):
    """A routine's lifecycle (spec 01 Cluster C)."""

    ACTIVE = "active"
    PAUSED = "paused"


class TriggerKind(StrEnum):
    """How a routine trigger fires (spec 01 Cluster C ``routine_trigger``)."""

    CRON = "cron"
    WEBHOOK = "webhook"
    MANUAL = "manual"


class RoutineRunStatus(StrEnum):
    """One firing's lifecycle (spec 01 Cluster C ``routine_run``)."""

    RECEIVED = "received"
    DISPATCHED = "dispatched"
    COALESCED = "coalesced"
    SUPPRESSED = "suppressed"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class Routine:
    """A cron template + owner + policies (spec 01 Cluster C ``routine``)."""

    id: str
    employee_id: str
    intent_template: str
    goal_id: str | None = None
    parent_task_id: str | None = None
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency_policy: RoutineConcurrency = RoutineConcurrency.SKIP_IF_ACTIVE
    catch_up_policy: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED
    status: RoutineStatus = RoutineStatus.ACTIVE
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RoutineTrigger:
    """A routine's schedule (spec 01 Cluster C ``routine_trigger``).

    ``next_run_at`` is the double-fire-guard target: firing is an optimistic ``UPDATE … WHERE
    next_run_at=<old>`` so two ticks can't fire the same edge.
    """

    id: str
    routine_id: str
    kind: TriggerKind = TriggerKind.CRON
    cron_expression: str | None = None
    timezone: str = "UTC"
    next_run_at: datetime | None = None
    last_fired_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class RoutineRun:
    """One firing → one task (spec 01 Cluster C ``routine_run``).

    Dispatch is exact-once via ``idempotency_key`` (partial-unique). ``coalesced_into_run_id`` points
    a folded firing at the survivor.
    """

    id: str
    routine_id: str
    trigger_id: str
    status: RoutineRunStatus = RoutineRunStatus.RECEIVED
    dispatch_fingerprint: str = ""
    idempotency_key: str | None = None
    linked_task_id: str | None = None
    coalesced_into_run_id: str | None = None
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
    proposed_revision: dict[str, object] | None = None  # a loosen staged for §5 approval (§1)


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


class MessageKind(StrEnum):
    """The intent of a mailbox message (spec 01 Cluster G ``message``)."""

    INSTRUCTION = "instruction"
    REPLY = "reply"
    ESCALATION = "escalation"
    FYI = "fyi"


@dataclass(frozen=True)
class Message:
    """A durable mailbox message (spec 01 Cluster G).

    Sender is an employee XOR a human (``from_employee_id`` / ``from_user_id``). A message does not
    run anything — the run-causing event is the wake the scheduler enqueues for ``to_employee_id``.
    """

    id: str
    to_employee_id: str
    body: str
    kind: MessageKind = MessageKind.INSTRUCTION
    from_employee_id: str | None = None
    from_user_id: str | None = None
    task_id: str | None = None
    read_at: datetime | None = None
    created_at: datetime | None = None


class RecoveryKind(StrEnum):
    """What flavour of stuckness a :class:`RecoveryAction` owns (spec 01 Cluster B, spec 02)."""

    MISSING_DISPOSITION = "missing_disposition"
    STRANDED = "stranded"
    WORKSPACE = "workspace"
    STALE_RUN_WATCHDOG = "stale_run_watchdog"
    GRAPH_LIVENESS = "graph_liveness"


class RecoveryStatus(StrEnum):
    """A recovery's lifecycle (spec 01 Cluster B, spec 02 §6).

    ``active``/``escalated`` are *open*; ``resolved``/``folded``/``superseded`` are terminal:
    ``resolved`` = owner acted; ``folded`` = the source resolved itself (false positive);
    ``superseded`` = a newer action replaced this one.
    """

    ACTIVE = "active"
    ESCALATED = "escalated"
    RESOLVED = "resolved"
    FOLDED = "folded"
    SUPERSEDED = "superseded"


class RecoveryOutcome(StrEnum):
    """How a recovery ended (spec 01 Cluster B)."""

    RESTORED = "restored"
    DELEGATED = "delegated"
    FALSE_POSITIVE = "false_positive"
    BLOCKED = "blocked"
    ESCALATED = "escalated"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class RecoveryAction:
    """Liveness-as-visibility — the first-class "who owns making this unstuck" (spec 01 Cluster B).

    At most one *open* (active/escalated) recovery exists per source task, and one per
    ``(source, cause, fingerprint)`` — both enforced by partial-unique indexes. ``recovery_task_id``
    is set only for an issue-backed independent repair. Attempts are bounded by ``max_attempts``.
    """

    id: str
    source_task_id: str
    kind: RecoveryKind
    recovery_task_id: str | None = None
    status: RecoveryStatus = RecoveryStatus.ACTIVE
    owner_employee_id: str | None = None
    owner_user_id: str | None = None
    previous_owner_employee_id: str | None = None
    return_owner_employee_id: str | None = None
    cause: str = ""
    fingerprint: str = ""
    evidence: dict[str, object] = field(default_factory=dict)
    next_action: str | None = None
    wake_policy: dict[str, object] = field(default_factory=dict)
    monitor_policy: dict[str, object] = field(default_factory=dict)
    attempt_count: int = 0
    max_attempts: int = 0
    timeout_at: datetime | None = None
    last_attempt_at: datetime | None = None
    resolved_at: datetime | None = None
    outcome: RecoveryOutcome | None = None
    resolution_note: str | None = None
    created_at: datetime | None = None


class MonitorStatus(StrEnum):
    """A monitor's one-shot lifecycle (spec 01 Cluster B ``monitor``)."""

    PENDING = "pending"
    FIRED = "fired"
    CLEARED = "cleared"
    EXHAUSTED = "exhausted"


class MonitorRecoveryPolicy(StrEnum):
    """What a monitor does when its attempts are exhausted (spec 01 Cluster B)."""

    WAKE_OWNER = "wake_owner"
    CREATE_RECOVERY = "create_recovery"
    ESCALATE = "escalate"


@dataclass(frozen=True)
class Monitor:
    """Deferred self-wake for a task waiting on an external system (spec 01 Cluster B).

    One-shot: on fire it is cleared and a ``monitor_due`` wake is queued; if the external thing still
    isn't done the assignee must **re-arm** with a new ``next_check_at``. Re-arming an exhausted
    monitor is rejected. At most one armed (pending) monitor per task. *Not* a recurring interval.
    ``external_ref`` is secret-adjacent — redacted before persist, omitted from wakes.
    """

    id: str
    task_id: str
    employee_id: str
    next_check_at: datetime | None = None
    status: MonitorStatus = MonitorStatus.PENDING
    notes: str | None = None
    external_ref: str | None = None
    timeout_at: datetime | None = None
    max_attempts: int = 1
    attempt_count: int = 0
    recovery_policy: MonitorRecoveryPolicy = MonitorRecoveryPolicy.WAKE_OWNER
    created_at: datetime | None = None
    fired_at: datetime | None = None


@dataclass(frozen=True)
class ArtifactRevision:
    """Immutable artifact history (spec 01 Cluster F ``artifact_revision``).

    Each row is a frozen snapshot of an :class:`Artifact` at one ``revision`` (monotonic per
    artifact, assigned by the repo on record). A revision is *the thing decomposition is authorized
    against* — :class:`DecompositionClaim` FKs its ``accepted_plan_revision_id`` here.
    """

    id: str
    artifact_id: str
    revision: int = 0
    resource_ref: dict[str, object] | None = None
    summary: str | None = None
    created_by_run_id: str | None = None
    created_at: datetime | None = None


class BudgetScope(StrEnum):
    """What a :class:`BudgetPolicy` caps (spec 01 Cluster E ``budget_policy``)."""

    COMPANY = "company"
    EMPLOYEE = "employee"


class BudgetThreshold(StrEnum):
    """Which gate a breach tripped (spec 01 Cluster E, spec 04 two-gate budgets)."""

    SOFT = "soft"
    HARD = "hard"


class BudgetIncidentStatus(StrEnum):
    """A breach record's lifecycle (spec 01 Cluster E ``budget_incident``)."""

    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class BudgetPolicy:
    """A spend cap for a scope (spec 01 Cluster E, spec 04). One per scope/metric/window.

    The soft gate warns at ``warn_percent`` of ``amount``; the hard gate (when ``hard_stop_enabled``)
    blocks and opens a hard :class:`BudgetIncident` that a human approval must clear.
    """

    id: str
    scope_type: BudgetScope
    scope_id: str
    amount: int
    metric: str = "cost_cents"
    warn_percent: int = 80
    hard_stop_enabled: bool = True
    window_kind: str = "monthly"
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BudgetIncident:
    """A budget breach record (spec 01 Cluster E). At most one open per policy/window/threshold.

    A hard breach attaches an :class:`Approval` (``approval_id``) — the gate a human resolves to let
    the blocked work proceed.
    """

    id: str
    policy_id: str
    threshold_type: BudgetThreshold
    amount_limit: int
    amount_observed: int
    window_start: datetime
    status: BudgetIncidentStatus = BudgetIncidentStatus.OPEN
    approval_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class CostEvent:
    """One immutable spend record (spec 01 Cluster E ``cost_event``).

    ``spent`` is recomputed live by summing cost_events on read — never trusted as a stored counter
    (the Paperclip rule).
    """

    id: str
    employee_id: str
    provider: str
    model: str
    cost_cents: int
    task_id: str | None = None
    run_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    occurred_at: datetime | None = None


class ActivityVerb(StrEnum):
    """A state transition worth auditing (spec 01 Cluster G ``activity``, spec 08 §5)."""

    ASSIGNED = "assigned"
    DECOMPOSED = "decomposed"
    SCRUM_PACKET = "scrum_packet"
    RECOVERED = "recovered"
    GATED = "gated"
    HIRED = "hired"
    FIRED = "fired"
    APPROVED = "approved"
    DENIED = "denied"
    REVISION_REQUESTED = "revision_requested"
    PROMOTED = "promoted"
    DOD_REVISED = "dod_revised"
    REVIEW_VERDICT = "review_verdict"


@dataclass(frozen=True)
class Activity:
    """One immutable row in the governance audit stream (spec 01 Cluster G, spec 08 §5).

    Append-only (no ``updated_at``). Actor is an employee XOR a human; both null means the kernel
    itself acted. ``trace_id`` correlates to the operational event stream / ``cost_event``.
    """

    id: str
    verb: ActivityVerb
    subject_kind: str
    subject_id: str
    actor_employee_id: str | None = None
    actor_user_id: str | None = None
    trace_id: str | None = None
    payload: Mapping[str, Any] = field(default_factory=dict)
    occurred_at: datetime | None = None


class ApprovalSubjectKind(StrEnum):
    """What an :class:`Approval` gates (spec 01 Cluster G ``approval``)."""

    BUDGET_INCIDENT = "budget_incident"
    TASK = "task"
    ARTIFACT = "artifact"
    EMPLOYEE = "employee"


class ApprovalAction(StrEnum):
    """The governed action an :class:`Approval` represents — the spec-04 §5 ``type`` (§5 governance).

    Orthogonal to :class:`ApprovalSubjectKind` (*what* is gated): ``action`` is *which org mutation*
    resolving the gate performs. The :class:`~chorus.governance.GovernanceResolver` dispatches on it to
    a registered handler. ``BUDGET_OVERRIDE`` is modelled for completeness but keeps resolving via the
    §3 budget enforcer.
    """

    HIRE_EMPLOYEE = "hire_employee"
    PLAN_APPROVAL = "plan_approval"
    BOARD_APPROVAL = "board_approval"
    BUDGET_OVERRIDE = "budget_override"
    LOOSEN_DOD = "loosen_dod"
    TASK_GATE = "task_gate"


class ApprovalStatus(StrEnum):
    """A human gate's verdict lifecycle (spec 01 Cluster G, spec 04 §5)."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    REVISION_REQUESTED = "revision_requested"
    EXPIRED = "expired"


class ApprovalGate(StrEnum):
    """How resolving a *task* approval acts on the task (spec 04 §5).

    Orthogonal to :class:`ApprovalSubjectKind` (which says *what* is gated): ``ACCEPTANCE`` means the
    approval **is** the task's acceptance (approve → done), ``AUTHORIZATION`` means it authorises the
    work to proceed (approve → todo). ``None`` for non-task gates (e.g. a budget incident).
    """

    ACCEPTANCE = "acceptance"
    AUTHORIZATION = "authorization"


@dataclass(frozen=True)
class Approval:
    """The durable human gate behind a hard-stop or role-declared approval (spec 01 Cluster G).

    A task needing sign-off sits ``blocked`` while this row is ``pending``; resolving it (approve /
    deny / expire) is what a human — or horizon, later — does to unblock. The gate is exact-once:
    at most one ``pending`` row per ``(subject_kind, subject_id)`` (partial-unique index).
    """

    id: str
    subject_kind: ApprovalSubjectKind
    subject_id: str
    reason: str
    action: ApprovalAction = ApprovalAction.TASK_GATE
    status: ApprovalStatus = ApprovalStatus.PENDING
    gate_kind: ApprovalGate | None = None
    decided_by_user_id: str | None = None
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime | None = None


class WakeReason(StrEnum):
    """Why a wake fired and who fires it (spec 03 §2)."""

    TASK_ASSIGNED = "task_assigned"
    DEPS_RESOLVED = "deps_resolved"
    CHILDREN_DONE = "children_done"
    MESSAGE = "message"
    CRON_DUE = "cron_due"
    MONITOR_DUE = "monitor_due"
    RECOVERY = "recovery"
    MANUAL = "manual"


class WakeStatus(StrEnum):
    """A wake's claim lifecycle (spec 01 Cluster C ``wake``)."""

    QUEUED = "queued"
    CLAIMED = "claimed"
    DONE = "done"


@dataclass(frozen=True)
class Wake:
    """The coalescing push inbox row (spec 01 Cluster C, spec 03 §2).

    ``coalesce_key`` (default ``employee:reason:task``) is the dedup key the partial-unique index
    enforces — a flurry of identical triggers folds into one *queued* wake (``coalesced_count``
    bumped), so the employee runs once.
    """

    id: str
    employee_id: str
    reason: WakeReason
    payload: Mapping[str, Any] = field(default_factory=dict)
    status: WakeStatus = WakeStatus.QUEUED
    coalesce_key: str | None = None
    coalesced_count: int = 0
    run_id: str | None = None
    created_at: datetime | None = None
    claimed_at: datetime | None = None
    finished_at: datetime | None = None


__all__ = [
    "Activity",
    "ActivityVerb",
    "Approval",
    "ApprovalStatus",
    "ApprovalSubjectKind",
    "Artifact",
    "ArtifactRevision",
    "ArtifactType",
    "BudgetIncident",
    "BudgetIncidentStatus",
    "BudgetPolicy",
    "BudgetScope",
    "BudgetThreshold",
    "CostEvent",
    "DecompositionClaim",
    "DecompositionStatus",
    "Dod",
    "DodStatus",
    "Goal",
    "GoalLevel",
    "Message",
    "MessageKind",
    "Monitor",
    "MonitorRecoveryPolicy",
    "MonitorStatus",
    "OriginKind",
    "RecoveryAction",
    "RecoveryKind",
    "RecoveryOutcome",
    "RecoveryStatus",
    "Routine",
    "RoutineCatchUp",
    "RoutineConcurrency",
    "RoutineRun",
    "RoutineRunStatus",
    "RoutineStatus",
    "RoutineTarget",
    "RoutineTrigger",
    "Run",
    "RunStatus",
    "Task",
    "TaskDependency",
    "TaskPriority",
    "TaskStatus",
    "Wake",
    "WakeReason",
    "WakeStatus",
]
