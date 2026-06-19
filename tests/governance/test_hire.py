"""hire_employee — the governed hire (§5 governance, Approach A), end to end.

A gated hire creates the employee ``pending`` (uninvokable) with its budget; the approval flips
activation: approve → ``active``, deny → ``terminated``, revise → stays ``pending``. With no policy the
hire is direct (today's behaviour). Exercised through the real resolver + ledger, and the facade.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.facade import Caps, Chorus
from chorus.governance import (
    ApprovalDecision,
    GovernancePolicy,
    GovernanceResolver,
    HireError,
)
from chorus.governance._actions import HireEmployeeAction
from chorus.ledger import (
    ApprovalAction,
    ApprovalStatus,
    ApprovalSubjectKind,
    BudgetScope,
    SqliteLedger,
)
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import EmployeeStatus, LedgerWorkforce

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "founder"


def _open_hire_gate(ledger: SqliteLedger, employee_id: str) -> str:
    approval = GovernanceResolver(ledger).open(
        action=ApprovalAction.HIRE_EMPLOYEE,
        subject_kind=ApprovalSubjectKind.EMPLOYEE,
        subject_id=employee_id,
        reason="hire",
    )
    return approval.id


def test_approve_activates_the_pending_employee(ledger: SqliteLedger) -> None:
    wf = LedgerWorkforce(ledger.employees)
    wf.hire(name="Ada", role="engineer", status=EmployeeStatus.PENDING)
    gate = _open_hire_gate(ledger, "ada")
    assert ledger.employees.get("ada").status is EmployeeStatus.PENDING  # type: ignore[union-attr]

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
    )

    assert ledger.employees.get("ada").status is EmployeeStatus.ACTIVE  # type: ignore[union-attr]


def test_deny_terminates_the_pending_employee(ledger: SqliteLedger) -> None:
    LedgerWorkforce(ledger.employees).hire(
        name="Bo", role="engineer", status=EmployeeStatus.PENDING
    )
    gate = _open_hire_gate(ledger, "bo")

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.DENY, decided_by_user_id=_USER, now=_NOW
    )

    assert ledger.employees.get("bo").status is EmployeeStatus.TERMINATED  # type: ignore[union-attr]


def test_revision_keeps_the_employee_pending(ledger: SqliteLedger) -> None:
    LedgerWorkforce(ledger.employees).hire(
        name="Cy", role="engineer", status=EmployeeStatus.PENDING
    )
    gate = _open_hire_gate(ledger, "cy")

    outcome = GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.REQUEST_REVISION, decided_by_user_id=_USER, now=_NOW
    )

    assert outcome.decision is ApprovalStatus.REVISION_REQUESTED
    assert ledger.employees.get("cy").status is EmployeeStatus.PENDING  # type: ignore[union-attr]


def test_open_rejects_a_non_pending_subject(ledger: SqliteLedger) -> None:
    LedgerWorkforce(ledger.employees).hire(name="Di", role="engineer")  # idle, not pending
    with pytest.raises(HireError):
        _open_hire_gate(ledger, "di")


def test_handler_action_kind() -> None:
    assert HireEmployeeAction.action is ApprovalAction.HIRE_EMPLOYEE


# -- through the facade ------------------------------------------------------------------------------


def _chorus(ledger: SqliteLedger, policy: GovernancePolicy) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=None,  # type: ignore[arg-type]
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
        governance_policy=policy,
    )


def test_facade_request_hire_gated_opens_a_pending_hire_with_budget(ledger: SqliteLedger) -> None:
    chorus = _chorus(ledger, GovernancePolicy(require_hire_approval=True))

    req = chorus.request_hire(name="Eve", role="engineer", budget_cents=5000)

    assert req.approval is not None and req.approval.action is ApprovalAction.HIRE_EMPLOYEE
    assert req.employee.status is EmployeeStatus.PENDING
    budgets = ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, "eve")
    assert len(budgets) == 1 and budgets[0].amount == 5000


def test_facade_request_hire_ungated_hires_directly(ledger: SqliteLedger) -> None:
    chorus = _chorus(ledger, GovernancePolicy())  # empty policy → no gate

    req = chorus.request_hire(name="Fae", role="engineer")

    assert req.approval is None
    assert req.employee.status is EmployeeStatus.IDLE
    assert ledger.approvals.pending() == []
