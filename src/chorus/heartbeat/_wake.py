"""The wake model + the tick's report shape (spec 03 §2, spec 10 §1).

A ``wake`` is *"run employee E because reason R, payload P."* Dispatch is
**push-only**: an employee runs only when a durable wake row exists (B2.3) — the
tick is the sole timer, and it exists to drain wakes, fire cron, and recover
crashes, never to make every employee re-check its inbox. Coalescing is a
database guarantee (the ``wake_queued_key_uq`` partial-unique index, spec 01),
not coordination code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class WakeReason(StrEnum):
    """Why a wake fired and who fires it (spec 03 §2 table)."""

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
    """The coalescing push inbox row (spec 01 Cluster C).

    ``coalesce_key`` (default ``employee:reason:task``) is the dedup key the
    partial-unique index enforces — a flurry of identical triggers folds into one
    queued wake (``coalesced_count`` bumped), so the employee runs once.
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


@dataclass(frozen=True)
class TickReport:
    """What one kernel pulse did (spec 03, spec 10 §1).

    A read projection of a single ``tick`` — the recovery sweep, cron firings,
    wakes drained, beats dispatched (kicked off async, *not* awaited), and how
    many dispatches a hard-stop budget blocked.
    """

    at: datetime
    recovered: int = 0
    routines_fired: int = 0
    wakes_dispatched: int = 0
    beats_started: int = 0
    blocked_by_budget: int = 0


__all__ = [
    "TickReport",
    "Wake",
    "WakeReason",
    "WakeStatus",
]
