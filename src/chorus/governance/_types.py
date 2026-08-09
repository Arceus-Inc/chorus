"""The governed-action seam types (§5 governance, Approach A).

A governed action is one small, dream-free unit that owns the org mutation behind an ``approval``: how
opening it parks/flags the subject, and what approving / denying / requesting-revision *does*. The
:class:`~chorus.governance.GovernanceResolver` is a thin dispatcher over a registry of these.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalStatus,
    AuthenticationMethod,
)


class ApprovalDecision(StrEnum):
    """The three ways a human resolves a gate (spec 04 §5). Maps 1:1 to a terminal status.

    ``HOLD`` is intentionally not a decision: :meth:`GovernanceResolver.hold_authenticated` records
    it as durable evidence while leaving the approval pending. These remain the terminal resolutions.
    """

    APPROVE = "approve"
    DENY = "deny"
    REQUEST_REVISION = "request_revision"

    @property
    def status(self) -> ApprovalStatus:
        """The terminal :class:`ApprovalStatus` this decision records."""
        return _DECISION_STATUS[self]


_DECISION_STATUS: dict[ApprovalDecision, ApprovalStatus] = {
    ApprovalDecision.APPROVE: ApprovalStatus.APPROVED,
    ApprovalDecision.DENY: ApprovalStatus.DENIED,
    ApprovalDecision.REQUEST_REVISION: ApprovalStatus.REVISION_REQUESTED,
}


@dataclass(frozen=True)
class HumanAuthorization:
    """Authenticated human context supplied to the public terminal-resolution API."""

    decision_id: str
    user_id: str
    method: AuthenticationMethod
    authenticated_at: datetime
    nonce: str
    decided_at: datetime
    request_id: str
    request_hash: str

    def __post_init__(self) -> None:
        for name, value in (
            ("authenticated_at", self.authenticated_at),
            ("decided_at", self.decided_at),
        ):
            if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
                raise ValueError(f"{name} must be a UTC datetime")
        if self.authenticated_at > self.decided_at:
            raise ValueError("authenticated_at must be at or before decided_at")


@dataclass(frozen=True)
class ActionOutcome:
    """What a handler's side-effect did: the gated subject's new status + how many wakes fired.

    ``subject_status`` is the ``.value`` of whatever typed status the subject carries (a task's
    :class:`TaskStatus`, an employee's :class:`EmployeeStatus`, …) — a string only at this generic
    seam; handlers compute it from typed enums and never branch on the string.
    """

    subject_status: str
    wakes_fired: int = 0


@runtime_checkable
class GovernedAction(Protocol):
    """One governed action — its open/approve/deny/revise org mutations (spec 04 §5).

    A handler holds the ledger it mutates; the resolver wraps every call in one atomic, audited
    transaction. Implementations live one-per-file under ``chorus/governance/_actions/``.
    """

    action: ApprovalAction

    def on_open(self, approval: Approval) -> None:
        """Park or flag the subject when the gate opens (e.g. block the task)."""
        ...

    def on_approve(self, approval: Approval) -> ActionOutcome: ...

    def on_deny(self, approval: Approval) -> ActionOutcome: ...

    def on_revise(self, approval: Approval) -> ActionOutcome: ...


__all__ = ["ActionOutcome", "ApprovalDecision", "GovernedAction", "HumanAuthorization"]
