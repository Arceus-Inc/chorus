"""The ``org.governance`` group (spec 14 §5.1) — open gates and resolve them.

The facade opened gates (request_hire / request_promotion) but couldn't resolve them; the group
closes the loop with ``resolve`` + the ``approvals`` inbox, all through the tested
``GovernanceResolver`` (atomic + audited).
"""

from __future__ import annotations

import pytest

from chorus.facade import Caps, Chorus
from chorus.governance import ApprovalDecision, GovernancePolicy, WorkforcePlanService
from chorus.ledger import (
    ApprovalGate,
    ManagementGrantDraft,
    PlannedEmployee,
    SqliteLedger,
    Task,
    WorkforcePlanDraft,
    WorkforcePlanStatus,
)
from chorus.observability import EventBus, LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import EmployeeStatus, LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: SqliteLedger, policy: GovernancePolicy | None = None) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=EventBus(),
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
        governance_policy=policy or GovernancePolicy(),
    )


def test_request_hire_gate_appears_in_approvals_then_resolve_activates() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger, GovernancePolicy(require_hire_approval=True))
        req = chorus.governance.request_hire(name="Eve", role="backend_engineer")
        assert req.approval is not None
        assert req.employee.status is EmployeeStatus.PENDING
        assert [a.id for a in chorus.governance.approvals()] == [req.approval.id]

        chorus.governance.resolve(req.approval.id, decision=ApprovalDecision.APPROVE, by="boss")
        assert chorus.governance.approvals() == []  # no longer pending
        activated = ledger.employees.get("eve")
        assert activated is not None and activated.status is not EmployeeStatus.PENDING
    finally:
        ledger.close()


def test_deny_a_hire_gate_terminates() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger, GovernancePolicy(require_hire_approval=True))
        req = chorus.governance.request_hire(name="Bo", role="backend_engineer")
        assert req.approval is not None
        chorus.governance.resolve(req.approval.id, decision=ApprovalDecision.DENY, by="boss")
        assert chorus.governance.approvals() == []
    finally:
        ledger.close()


def test_open_task_gate_then_resolve_clears_the_inbox() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        ledger.tasks.submit(Task(id="t1", intent="risky deploy"))
        approval = chorus.governance.open_gate(
            "t1", gate_kind=ApprovalGate.ACCEPTANCE, reason="needs sign-off"
        )
        assert approval.id in {a.id for a in chorus.governance.approvals()}
        chorus.governance.resolve(approval.id, decision=ApprovalDecision.APPROVE, by="boss")
        assert chorus.governance.approvals() == []
    finally:
        ledger.close()


def test_human_governance_facade_applies_a_ceo_workforce_proposal() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="CEO", role="ceo")
        draft = WorkforcePlanDraft(
            rationale="One analyst is sufficient for the approved discovery goal.",
            confidence=0.9,
            source_goal_ids=("goal-1",),
            employees=(
                PlannedEmployee(
                    ref="analyst",
                    name="Analyst",
                    profession="analyst",
                    reports_to_ref="ceo",
                ),
            ),
            management_grants=(
                ManagementGrantDraft(
                    employee_ref="ceo",
                    can_lead=True,
                    can_subdelegate=False,
                    max_delegation_depth=1,
                    max_team_size=2,
                    allowed_professions=("analyst",),
                ),
            ),
        )
        proposed = WorkforcePlanService(
            ledger,
            workforce=LedgerWorkforce(ledger.employees),
            roles=RoleRegistry.from_plugins(default_roles()),
        ).propose(draft, proposed_by_employee_id="ceo")

        applied = chorus.governance.approve_workforce_plan(proposed.id, by="founder")

        assert applied.status is WorkforcePlanStatus.APPLIED
        assert ledger.employees.get("analyst") is not None
        assert chorus.governance.workforce_plans()[-1] == applied
        assert chorus.governance.staffing_requests() == []
    finally:
        ledger.close()
