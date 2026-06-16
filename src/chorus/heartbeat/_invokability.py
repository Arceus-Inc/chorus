"""The invokability gate — Gate 0 of beat dispatch (spec 06 §3).

Budgets answer *"can this scope afford a beat?"*; invokability answers the prior question
*"should this identity run **at all**?"*. An employee is **not invokable** when it is terminated,
paused, or hangs off a broken org chain (a missing, cyclic, or terminated manager). The scheduler
consults this before checkout so a dead or orphaned identity never starts a beat.

The classifier is pure: workforce + employee id in, an :class:`InvokabilityBlock` (or ``None`` =
"go") out. The ``cancels`` flag tells the dispatcher whether to *cancel* the wake and its task
(terminated / orphaned — the identity is gone for good) or merely *hold it back* (paused — the wake
waits for a resume).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chorus.errors import UnknownEmployee
from chorus.workforce import EmployeeStatus, Workforce

# A defensive ceiling on the manager walk — far beyond any real org depth, so a corrupt chain that
# slips a cycle past the visited-set check still terminates rather than spinning.
_MAX_CHAIN_DEPTH = 1000


class InvokabilityReason(StrEnum):
    """Why an employee is not invokable this pulse (spec 06 §3)."""

    PAUSED = "paused"
    TERMINATED = "terminated"
    INVALID_ORG_CHAIN = "invalid_org_chain"


@dataclass(frozen=True)
class InvokabilityBlock:
    """A non-invokable verdict: the ``reason`` plus whether it *cancels* the wake.

    ``cancels=True`` is terminal (the identity is gone — cancel the wake and its task);
    ``cancels=False`` is transient (paused — release the wake to wait for a resume).
    """

    reason: InvokabilityReason
    cancels: bool


def invokability_block(workforce: Workforce, employee_id: str) -> InvokabilityBlock | None:
    """Classify whether ``employee_id`` may start a beat — ``None`` means yes (spec 06 §3)."""
    try:
        employee = workforce.get(employee_id)
    except (KeyError, UnknownEmployee):
        # The wake names an employee the org no longer knows — orphaned, cancel it.
        return InvokabilityBlock(InvokabilityReason.INVALID_ORG_CHAIN, cancels=True)

    if employee.status is EmployeeStatus.TERMINATED:
        return InvokabilityBlock(InvokabilityReason.TERMINATED, cancels=True)
    if employee.status is EmployeeStatus.PAUSED:
        return InvokabilityBlock(InvokabilityReason.PAUSED, cancels=False)

    # Walk up the reports-to chain: a missing, cyclic, or terminated manager orphans the report.
    seen = {employee.id}
    current = employee
    for _ in range(_MAX_CHAIN_DEPTH):
        manager_id = current.reports_to
        if manager_id is None:
            return None  # reached a root cleanly
        if manager_id in seen:
            return InvokabilityBlock(InvokabilityReason.INVALID_ORG_CHAIN, cancels=True)
        seen.add(manager_id)
        try:
            current = workforce.get(manager_id)
        except (KeyError, UnknownEmployee):
            return InvokabilityBlock(InvokabilityReason.INVALID_ORG_CHAIN, cancels=True)
        if current.status is EmployeeStatus.TERMINATED:
            return InvokabilityBlock(InvokabilityReason.INVALID_ORG_CHAIN, cancels=True)
    return InvokabilityBlock(InvokabilityReason.INVALID_ORG_CHAIN, cancels=True)


__all__ = [
    "InvokabilityBlock",
    "InvokabilityReason",
    "invokability_block",
]
