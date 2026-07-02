"""Governance row models — activity, approvals, messages, recovery, monitors."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from chorus.ledger._models._enums import (
    ActivityVerb,
    ApprovalAction,
    ApprovalGate,
    ApprovalStatus,
    ApprovalSubjectKind,
    MessageKind,
    MonitorRecoveryPolicy,
    MonitorStatus,
    RecoveryKind,
    RecoveryOutcome,
    RecoveryStatus,
)


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
