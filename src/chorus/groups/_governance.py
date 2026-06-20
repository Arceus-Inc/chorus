"""``org.governance`` — the governed-action surface (spec 14 §5.1, spec 04 §5).

Opening gates (hire, promotion, plan, task) and resolving them (approve / deny / request-revision).
The facade *opened* gates but couldn't *resolve* them; this group closes the loop. Every mutation runs
through the tested :class:`GovernanceResolver` (atomic + audited, fail-closed on the registry).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from chorus.errors import OrgInvariantViolation
from chorus.governance import ApprovalDecision, GovernancePolicy, GovernanceResolver, ResolveOutcome
from chorus.ledger import (
    Approval,
    ApprovalAction,
    ApprovalGate,
    ApprovalSubjectKind,
    BudgetPolicy,
    BudgetScope,
    SqliteLedger,
)
from chorus.roles import RoleRegistry
from chorus.workforce import Employee, EmployeeStatus, Workforce


@dataclass(frozen=True)
class HireRequest:
    """The result of :meth:`GovernanceFacade.request_hire` (spec 04 §5 ``hire_employee``).

    ``approval`` is the pending ``hire_employee`` gate when the policy required sign-off, else ``None``
    (the employee was hired directly and is already active)."""

    employee: Employee
    approval: Approval | None


class GovernanceFacade:
    """The ``org.governance`` surface — request/open gates, resolve them, read the open inbox."""

    def __init__(
        self,
        ledger: SqliteLedger,
        workforce: Workforce,
        roles: RoleRegistry,
        policy: GovernancePolicy,
    ) -> None:
        self._ledger = ledger
        self._workforce = workforce
        self._roles = roles
        self._policy = policy
        self._resolver = GovernanceResolver(ledger)

    def request_hire(
        self, *, name: str, role: str, reports_to: str | None = None, budget_cents: int | None = None
    ) -> HireRequest:
        """Hire an employee, gated by policy (spec 04 §5 ``hire_employee``).

        When ``policy.hire_gate_required()``, the employee is created ``pending`` (uninvokable) with its
        budget policy and a ``hire_employee`` approval is opened — a human approves (→ ``active``) or
        denies (→ ``terminated``). Otherwise the employee is hired directly (the empty default policy
        reproduces a plain hire)."""
        if role not in self._roles:
            raise OrgInvariantViolation(f"unknown role {role!r}")
        gated = self._policy.hire_gate_required()
        status = EmployeeStatus.PENDING if gated else EmployeeStatus.IDLE
        employee = self._workforce.hire(name=name, role=role, reports_to=reports_to, status=status)
        if budget_cents is not None:
            self._create_employee_budget(employee.id, budget_cents)
        if not gated:
            return HireRequest(employee=employee, approval=None)
        approval = self._resolver.open(
            action=ApprovalAction.HIRE_EMPLOYEE,
            subject_kind=ApprovalSubjectKind.EMPLOYEE,
            subject_id=employee.id,
            reason=f"hire {name} as {role}",
        )
        return HireRequest(employee=employee, approval=approval)

    def request_promotion(self, artifact_id: str) -> Approval | None:
        """Promote a landed artifact to the board, gated by policy (spec 04 §5 ``board_approval``).

        Opens a ``board_approval`` gate when ``policy.board_gate_required(<class>)``; else ``None``
        (ungated). Raises ``OrgInvariantViolation`` if the artifact is unknown."""
        artifact = self._ledger.artifacts.get(artifact_id)
        if artifact is None:
            raise OrgInvariantViolation(f"no such artifact {artifact_id!r}")
        if not self._policy.board_gate_required(artifact.type.value):
            return None
        return self._resolver.open(
            action=ApprovalAction.BOARD_APPROVAL,
            subject_kind=ApprovalSubjectKind.ARTIFACT,
            subject_id=artifact_id,
            reason=f"promote {artifact.type.value} to the board",
        )

    def open_gate(self, task_id: str, *, gate_kind: ApprovalGate, reason: str) -> Approval:
        """Open a task gate (a human must sign off before the task may proceed)."""
        return self._resolver.open_task_gate(task_id, gate_kind=gate_kind, reason=reason)

    def open_plan_gate(self, parent_id: str, *, reason: str) -> Approval:
        """Open a plan-approval gate on a parent task's decomposition."""
        return self._resolver.open_plan_gate(parent_id, reason=reason)

    def resolve(self, approval_id: str, *, decision: ApprovalDecision, by: str) -> ResolveOutcome:
        """Resolve a pending gate — its handler performs the org mutation, atomic + audited.

        Raises ``GovernanceError`` on an unknown approval or one no longer pending."""
        return self._resolver.resolve(
            approval_id, decision=decision, decided_by_user_id=by, now=datetime.now(UTC)
        )

    def approvals(self) -> list[Approval]:
        """The open-gate inbox — every pending approval awaiting a decision."""
        return self._ledger.approvals.pending()

    def _create_employee_budget(self, employee_id: str, amount_cents: int) -> None:
        self._ledger.budget_policies.create(
            BudgetPolicy(
                id=f"bp_{uuid.uuid4().hex[:12]}",
                scope_type=BudgetScope.EMPLOYEE,
                scope_id=employee_id,
                amount=amount_cents,
            )
        )


__all__ = ["GovernanceFacade", "HireRequest"]
