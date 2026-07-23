"""Scheduling row models — Run, Wake, and the Routine family (Clusters B/C)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from chorus.ledger._models._enums import (
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRunStatus,
    RoutineStatus,
    RoutineTarget,
    RunStatus,
    TriggerKind,
    WakeReason,
    WakeStatus,
)


@dataclass(frozen=True)
class Routine:
    """A cron template + owner + policies + revision head (spec 01 Cluster C ``routine``).

    ``env`` binds secret *refs* (never raw values, spec 13 §2.1); ``routine_key`` is the stable
    identity a plugin reconcile upserts on (spec 13 §5); ``latest_revision_id`` / ``latest_revision_no``
    point at the live ``routine_revision`` head (spec 13 §2.2).
    """

    id: str
    employee_id: str
    intent_template: str
    goal_id: str | None = None
    parent_task_id: str | None = None
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency_policy: RoutineConcurrency = RoutineConcurrency.COALESCE  # M4 S1: safe-by-default
    catch_up_policy: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED
    status: RoutineStatus = RoutineStatus.ACTIVE
    env: dict[str, str] | None = None
    routine_key: str | None = None
    latest_revision_id: str | None = None
    latest_revision_no: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class RoutineRevision:
    """One immutable version of a routine's definition (spec 01 Cluster C ``routine_revision``).

    Append-only: ``revise`` writes a new ``revision_no = head + 1``; ``restore`` writes a new head
    copied from an earlier revision with ``restored_from_revision_id`` recording the provenance. A
    firing pins the revision it ran under, so an edit never re-judges work already in flight.
    """

    id: str
    routine_id: str
    revision_no: int
    intent_template: str
    target: RoutineTarget = RoutineTarget.SPAWN_TASK
    concurrency_policy: RoutineConcurrency = RoutineConcurrency.COALESCE
    catch_up_policy: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED
    env: dict[str, str] | None = None
    change_summary: str | None = None
    restored_from_revision_id: str | None = None
    created_at: datetime | None = None


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
    routine_revision_id: str | None = None  # the routine_revision this firing fired under (§2.3)
    created_at: datetime | None = None


@dataclass(frozen=True)
class Run:
    """One beat — one ``dream.run_task`` invocation, kept THIN (spec 01 Cluster C ``run``)."""

    id: str
    employee_id: str
    task_id: str
    principal_kind: str = "employee"
    system_principal_id: str | None = None
    wake_id: str | None = None
    status: RunStatus = RunStatus.QUEUED
    lease_expires_at: datetime | None = None
    liveness_state: str | None = None
    continuation_attempt: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: dict[str, object] = field(default_factory=dict)
    usage: dict[str, object] = field(default_factory=dict)

    @property
    def principal_id(self) -> str:
        """The canonical actor, distinct from the employee host used for scheduling and costs."""
        if self.principal_kind == "system" and self.system_principal_id is not None:
            return self.system_principal_id
        return self.employee_id


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
