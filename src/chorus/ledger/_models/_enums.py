"""The ledger's enum vocabulary — every StrEnum the row models use (spec 01)."""

from __future__ import annotations

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
    REJECTED = "rejected"  # terminal: a reviewer blocked the deliverable (M3 load-bearing Reviewer)


class TaskPriority(StrEnum):
    """Dispatch priority band (spec 03 §3 sort key)."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExecutionMode(StrEnum):
    """The persisted execution contract selected for a task (M8 §5.5)."""

    DELIVERY = "delivery"
    DELEGATION = "delegation"


class TeamStatus(StrEnum):
    """Lifecycle of a durable delegation team (M8 §5.4)."""

    FORMING = "forming"
    ACTIVE = "active"
    BLOCKED = "blocked"
    ARCHIVED = "archived"


class TeamMembershipRole(StrEnum):
    """Responsibility inside a Team, independent of profession."""

    LEAD = "lead"
    MEMBER = "member"


class DelegationContractStatus(StrEnum):
    """Lifecycle of a persisted delegation contract (M8 §5.6)."""

    FORMING = "forming"
    DELEGATED = "delegated"
    INTEGRATING = "integrating"
    VERIFYING = "verifying"
    DONE = "done"
    BLOCKED = "blocked"


class OriginKind(StrEnum):
    """What spawned a task — keys the partial-unique exact-once indexes (spec 01)."""

    MANUAL = "manual"
    ROUTINE_EXECUTION = "routine_execution"
    DECOMPOSITION = "decomposition"
    STRANDED_RECOVERY = "stranded_recovery"
    STALE_RUN_EVAL = "stale_run_eval"
    PRODUCTIVITY_REVIEW = "productivity_review"
    HORIZON_INTAKE = "horizon_intake"  # opened by the horizon strategy layer (spec 00 §5a / 10 §5)


class RunStatus(StrEnum):
    """One beat's lifecycle (spec 01 Cluster C ``run``)."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


class GoalLevel(StrEnum):
    """The alignment tree levels (spec 01 Cluster D ``goal``).

    The coarse org levels (company/team/employee/task) plus ``goal`` — the level the horizon strategy
    layer writes for the Decision -> Goal -> Task spine. Decisions themselves are horizon-native and
    never become goal rows (chorus only ever sees goals + tasks). Additive: chorus does not act on
    ``level`` (it schedules by deps + caps + priority), so the vocabulary is horizon's to shape.
    """

    COMPANY = "company"
    TEAM = "team"
    EMPLOYEE = "employee"
    TASK = "task"
    GOAL = "goal"  # the node horizon authors under a (horizon-only) Decision


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


class DecompositionStatus(StrEnum):
    """A fan-out claim's lifecycle (spec 01 Cluster A ``decomposition_claim``)."""

    IN_FLIGHT = "in_flight"
    COMPLETED = "completed"


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


class MessageKind(StrEnum):
    """The intent of a mailbox message (spec 01 Cluster G ``message``)."""

    INSTRUCTION = "instruction"
    REPLY = "reply"
    ESCALATION = "escalation"
    FYI = "fyi"


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


class ActivityVerb(StrEnum):
    """A state transition worth auditing (spec 01 Cluster G ``activity``, spec 08 §5)."""

    ASSIGNED = "assigned"
    DECOMPOSED = "decomposed"
    PROFILE_GRANTED = "profile_granted"
    PROFILE_REVOKED = "profile_revoked"
    TEAM_FORMED = "team_formed"
    TEAM_ACTIVATED = "team_activated"
    TEAM_ARCHIVED = "team_archived"
    TEAM_MEMBER_ADDED = "team_member_added"
    TEAM_MEMBER_REMOVED = "team_member_removed"
    DELEGATION_CREATED = "delegation_created"
    DELEGATION_STATUS_CHANGED = "delegation_status_changed"
    LEAD_ACCEPTED = "lead_accepted"
    PARENT_VERIFIED = "parent_verified"
    REORG_REFUSED = "reorg_refused"
    SCRUM_PACKET = "scrum_packet"
    WORKFORCE_PLAN_PROPOSED = "workforce_plan_proposed"
    WORKFORCE_PLAN_REVISED = "workforce_plan_revised"
    WORKFORCE_PLAN_APPLIED = "workforce_plan_applied"
    WORKFORCE_PLAN_REJECTED = "workforce_plan_rejected"
    STAFFING_REQUESTED = "staffing_requested"
    STAFFING_REQUEST_FULFILLED = "staffing_request_fulfilled"
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


class ApprovalSubjectKind(StrEnum):
    """What an :class:`Approval` gates (spec 01 Cluster G ``approval``)."""

    BUDGET_INCIDENT = "budget_incident"
    TASK = "task"
    ARTIFACT = "artifact"
    EMPLOYEE = "employee"
    ROLLOUT = "rollout"


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
    PROMOTE_ROLLOUT = "promote_rollout"


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
