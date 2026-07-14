"""Adapt Dream's delegated-work port to Chorus root delegation intake."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dream.contracts.delegation import (
    DelegatedWorkRef,
    DelegatedWorkRequest,
    StaffingBlocked,
)

if TYPE_CHECKING:
    from chorus.facade import Chorus
    from chorus.ledger import SqliteLedger


class DelegatedIntakeAdapter:
    """Select a lead and create one idempotent delegated root through Chorus."""

    def __init__(
        self,
        chorus: Chorus,
        ledger: SqliteLedger,
        *,
        company_id: str,
    ) -> None:
        from chorus.lifecycle import LeadSelector

        self._chorus = chorus
        self._ledger = ledger
        self._selector = LeadSelector(ledger, company_id=company_id)

    def submit_delegated(
        self, request: DelegatedWorkRequest
    ) -> DelegatedWorkRef | StaffingBlocked:
        """Return the original durable identities on retry, or create them once."""
        existing = self._existing_ref(request.origin_fingerprint)
        if existing is not None:
            return existing

        selected = self._selector.select(request)
        if isinstance(selected, StaffingBlocked):
            return selected

        from chorus.ledger import ExecutionMode, OriginKind, TaskPriority

        task = self._chorus.submit(
            request.intent,
            assignee=selected.id,
            priority=TaskPriority(request.priority),
            goal_id=request.goal_id,
            origin_kind=OriginKind.HORIZON_INTAKE,
            origin_fingerprint=request.origin_fingerprint,
            execution_mode=ExecutionMode.DELEGATION,
            delegation_max_team_size=request.max_team_size,
            delegation_spend_limit_cents=request.spend_limit_cents,
        )
        persisted = self._ledger.tasks.get(task.id)
        if (
            persisted is None
            or persisted.team_id is None
            or persisted.assignee_employee_id is None
        ):
            raise RuntimeError("delegated root was created without durable team and lead identities")
        return DelegatedWorkRef(
            root_task_id=persisted.id,
            team_id=persisted.team_id,
            lead_id=persisted.assignee_employee_id,
        )

    def _existing_ref(self, origin_fingerprint: str) -> DelegatedWorkRef | None:
        from chorus.ledger import OriginKind

        if not origin_fingerprint:
            return None
        task = self._ledger.tasks.find_by_origin(
            OriginKind.HORIZON_INTAKE, origin_fingerprint
        )
        if task is None:
            return None
        if task.team_id is None or task.assignee_employee_id is None:
            raise RuntimeError("existing delegated intake is missing team or lead identity")
        return DelegatedWorkRef(
            root_task_id=task.id,
            team_id=task.team_id,
            lead_id=task.assignee_employee_id,
        )


__all__ = ["DelegatedIntakeAdapter"]