"""Liveness & recovery — "who owns making this unstuck" (spec 02).

Recovery is **liveness-as-visibility**: a non-terminal task that has lost its
action-path primitive becomes a first-class :class:`RecoveryAction` naming an
owner, a cause, and the next move — surfaced as a card, never silently dropped.
Stale-lock clearing is *crash recovery, not retry*: a checkout ``409`` is a real
live owner, so the caller stops (spec 01 invariant 4). The tick runs this sweep
*before* new dispatch so a crashed beat is reaped first (spec 03 §3a).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class RecoveryKind(StrEnum):
    """Why a recovery opened (spec 01 Cluster B ``recovery_action.kind``)."""

    MISSING_DISPOSITION = "missing_disposition"
    STRANDED = "stranded"
    WORKSPACE = "workspace"
    STALE_RUN_WATCHDOG = "stale_run_watchdog"
    GRAPH_LIVENESS = "graph_liveness"


class RecoveryStatus(StrEnum):
    """A recovery's lifecycle (spec 01 Cluster B)."""

    ACTIVE = "active"
    ESCALATED = "escalated"
    RESOLVED = "resolved"


@dataclass(frozen=True)
class RecoveryAction:
    """The durable "who owns the next move" row (spec 01 Cluster B, spec 02 §6).

    At most one open recovery per source task (and per ``(source, cause,
    fingerprint)``) — the partial-unique indexes make that a database guarantee.
    ``evidence`` is bounded + redacted; ``external_ref``-class data never lands here.
    """

    id: str
    source_task_id: str
    kind: RecoveryKind
    status: RecoveryStatus = RecoveryStatus.ACTIVE
    owner_employee_id: str | None = None
    owner_user_id: str | None = None
    cause: str = ""
    fingerprint: str = ""
    next_action: str = ""
    attempt_count: int = 0
    max_attempts: int = 3
    recovery_task_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    timeout_at: datetime | None = None
    resolved_at: datetime | None = None


class RecoveryReconciler:
    """The tick's recovery sweep (spec 02, spec 03 §3a).

    Reaps stale board leases, reconciles stranded work (bounded: one wake), and
    opens/updates :class:`RecoveryAction` rows. Recovery-owner selection only
    *recommends* an owner (assignee → reporting chain → creator chain → root) —
    it **never auto-reassigns** (spec 02 §8).
    """

    def __init__(self, *, max_attempts: int = 3) -> None:
        self.max_attempts = max_attempts

    def reconcile(self, now: datetime) -> int:
        """Run one recovery pass; return the number of stranded/stale items handled."""
        raise NotImplementedError("spec 02 §6/§9: reap stale leases, reconcile stranded, open cards")

    def open_or_update(self, source_task_id: str, *, kind: RecoveryKind, cause: str) -> RecoveryAction:
        """Open a recovery card (or update the existing one) for a stuck task (spec 02 §6)."""
        raise NotImplementedError("spec 02 §6: exact-once recovery per source/cause/fingerprint")


__all__ = [
    "RecoveryAction",
    "RecoveryKind",
    "RecoveryReconciler",
    "RecoveryStatus",
]
