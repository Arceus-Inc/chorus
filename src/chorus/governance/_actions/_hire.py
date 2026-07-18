"""The hire-employee governed action (§5 governance).

A governed hire creates the employee ``pending`` (uninvokable) and its budget policy up front; this
gate only flips activation: approve → ``active``, deny → ``terminated``. ``revise`` keeps the employee
``pending`` so the requester can amend the offer (e.g. re-hire with a new budget) under a fresh gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from chorus.governance._errors import GovernanceError
from chorus.governance._types import ActionOutcome
from chorus.ledger import Approval, ApprovalAction
from chorus.workforce import EmployeeStatus

if TYPE_CHECKING:
    from chorus.ledger import Ledger


class HireError(GovernanceError):
    """A hire gate whose subject employee is missing or not ``pending``."""


class HireEmployeeAction:
    """The ``hire_employee`` handler — activate or terminate a pending employee."""

    action = ApprovalAction.HIRE_EMPLOYEE

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    def on_open(self, approval: Approval) -> None:
        employee = self._ledger.employees.get(approval.subject_id)
        if employee is None or employee.status is not EmployeeStatus.PENDING:
            raise HireError(f"hire gate subject {approval.subject_id!r} is not a pending employee")

    def on_approve(self, approval: Approval) -> ActionOutcome:
        self._ledger.employees.set_status(approval.subject_id, EmployeeStatus.ACTIVE)
        return ActionOutcome(EmployeeStatus.ACTIVE.value)

    def on_deny(self, approval: Approval) -> ActionOutcome:
        self._ledger.employees.set_status(approval.subject_id, EmployeeStatus.TERMINATED)
        return ActionOutcome(EmployeeStatus.TERMINATED.value)

    def on_revise(self, approval: Approval) -> ActionOutcome:
        return ActionOutcome(EmployeeStatus.PENDING.value)  # stays pending; amend + re-open


__all__ = ["HireEmployeeAction", "HireError"]
