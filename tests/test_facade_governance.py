"""The ``org.governance`` group (spec 14 §5.1) — open gates and resolve them.

The facade opened gates (request_hire / request_promotion) but couldn't resolve them; the group
closes the loop with ``resolve`` + the ``approvals`` inbox, all through the tested
``GovernanceResolver`` (atomic + audited).
"""

from __future__ import annotations

import pytest

from chorus.facade import Caps, Chorus
from chorus.governance import ApprovalDecision, GovernancePolicy
from chorus.ledger import ApprovalGate, SqliteLedger, Task
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
        req = chorus.governance.request_hire(name="Eve", role="engineer")
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
        req = chorus.governance.request_hire(name="Bo", role="engineer")
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
