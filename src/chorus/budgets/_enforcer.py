"""The two-gate budget enforcer (spec 04 §3).

One object over the budget repos, no stored pause flag — *paused* is derived from an open hard
``budget_incident`` (which persists across window rollover), and *over* from live spend ≥ the cap.

- **Gate 1** :meth:`BudgetEnforcer.invocation_block` — pre-dispatch: is this beat's scope paused or
  over? Company first, then employee. Returns a :class:`BlockReason` or ``None``.
- **Gate 2** :meth:`BudgetEnforcer.on_cost_event` — react to a recorded cost event: at ``warn_percent``
  raise a soft incident (notify), at the cap (with ``hard_stop_enabled``) raise a hard incident paired
  with an approval, pause the scope, and kill its in-flight runs + pending wakes.
- **Resolution** is human-only: :meth:`raise_budget_and_resume` (cap must exceed observed) or
  :meth:`dismiss` (scope stays paused).
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

from chorus.budgets._window import BudgetWindow, window_start
from chorus.ids import mint_id
from chorus.ledger._models import (
    Approval,
    ApprovalSubjectKind,
    BudgetIncident,
    BudgetPolicy,
    BudgetScope,
    BudgetThreshold,
)

if TYPE_CHECKING:
    from chorus.ledger import Ledger
    from chorus.ledger._models import CostEvent

_PERCENT = 100
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)  # the pinned window_start for a lifetime (``total``) cap
_COST_METRIC = "cost_cents"  # the only metric this enforcer aggregates (spend in cents)


class BlockReason(StrEnum):
    """Why Gate 1 blocked a beat (spec 04 §3). Company reasons outrank employee reasons."""

    COMPANY_PAUSED = "company_paused"
    COMPANY_OVER = "company_over"
    EMPLOYEE_PAUSED = "employee_paused"
    EMPLOYEE_OVER = "employee_over"


class BudgetEnforcer:
    """Enforces the two-gate hard-stop over a ledger's budget repos for one company (spec 04 §3)."""

    def __init__(self, ledger: Ledger, *, company_id: str) -> None:
        self._ledger = ledger
        self._company_id = company_id

    # -- Gate 1: proactive pre-invocation block ---------------------------------------------------

    def invocation_block(self, employee_id: str, *, now: datetime) -> BlockReason | None:
        """Block reason if a beat for ``employee_id`` must not start — else ``None`` (spec 04 §3).

        Precedence is company-before-employee and, within a scope, paused-before-over: the scope's
        paused/over state is computed across *all* its policies first, so a paused policy is never
        masked by an over policy that merely sorts earlier.
        """
        company = self._cost_policies(BudgetScope.COMPANY, self._company_id)
        if any(self._is_paused(policy) for policy in company):
            return BlockReason.COMPANY_PAUSED
        if any(self._is_over(policy, now) for policy in company):
            return BlockReason.COMPANY_OVER
        employee = self._cost_policies(BudgetScope.EMPLOYEE, employee_id)
        if any(self._is_paused(policy) for policy in employee):
            return BlockReason.EMPLOYEE_PAUSED
        if any(self._is_over(policy, now) for policy in employee):
            return BlockReason.EMPLOYEE_OVER
        return None

    # -- Gate 2: reactive auto-pause + kill on a cost event ---------------------------------------

    def on_cost_event(self, event: CostEvent, *, now: datetime) -> list[BudgetIncident]:
        """React to a recorded cost event: raise any soft/hard incidents and kill on a hard breach."""
        raised: list[BudgetIncident] = []
        for policy in self._policies_for(event.employee_id):
            incident = self._evaluate(policy, now=now)
            if incident is not None:
                raised.append(incident)
        return raised

    # -- resolution (human-only) ------------------------------------------------------------------

    def raise_budget_and_resume(
        self, policy_id: str, new_amount: int, *, now: datetime, decided_by_user_id: str
    ) -> None:
        """Raise the cap above observed spend and clear the hard incident — the resume path.

        Raises ``ValueError`` if ``new_amount`` does not exceed the live observed spend (resuming
        under the breach would just re-trip the gate).
        """
        policy = self._require_policy(policy_id)
        observed = self._observed_spend(policy, now)
        if new_amount <= observed:
            raise ValueError(f"new budget {new_amount} must exceed observed spend {observed}")
        # Atomic: raising the cap, approving the request, and resolving the incident commit together
        # (or not at all), so a failure mid-resume never leaves a raised cap with the scope still paused.
        with self._ledger.transaction():
            self._ledger.budget_policies.set_amount(policy_id, new_amount)
            incident = self._open_hard_incident(policy_id)
            if incident is not None and incident.approval_id is not None:
                self._ledger.approvals.approve(
                    incident.approval_id, decided_by_user_id=decided_by_user_id
                )
                self._ledger.budget_incidents.resolve(incident.id)

    def dismiss(self, incident_id: str, *, decided_by_user_id: str) -> None:
        """Decline to resume: deny the approval; the incident stays open so the scope stays paused."""
        incident = self._ledger.budget_incidents.get(incident_id)
        if incident is None:
            raise KeyError(incident_id)
        if incident.approval_id is not None:
            self._ledger.approvals.deny(incident.approval_id, decided_by_user_id=decided_by_user_id)

    # -- internals --------------------------------------------------------------------------------

    def _cost_policies(self, scope_type: BudgetScope, scope_id: str) -> list[BudgetPolicy]:
        """A scope's policies that meter spend in cents — non-cost metrics (e.g. tokens) are skipped,
        since this enforcer only aggregates ``cost_event`` cents (spec 04 §3)."""
        return [
            policy
            for policy in self._ledger.budget_policies.by_scope(scope_type, scope_id)
            if policy.metric == _COST_METRIC
        ]

    def _policies_for(self, employee_id: str) -> list[BudgetPolicy]:
        return [
            *self._cost_policies(BudgetScope.EMPLOYEE, employee_id),
            *self._cost_policies(BudgetScope.COMPANY, self._company_id),
        ]

    def _evaluate(self, policy: BudgetPolicy, *, now: datetime) -> BudgetIncident | None:
        observed = self._observed_spend(policy, now)
        if policy.hard_stop_enabled and observed >= policy.amount:
            return self._raise_hard(policy, observed, now)
        if observed >= policy.amount * policy.warn_percent // _PERCENT:
            return self._raise_soft(policy, observed, now)
        return None

    def _raise_hard(
        self, policy: BudgetPolicy, observed: int, now: datetime
    ) -> BudgetIncident | None:
        if self._open_hard_incident(policy.id) is not None:
            return None  # already paused — the hard incident persists across windows (idempotent)
        incident_id = mint_id()
        self._ledger.budget_incidents.open(
            BudgetIncident(
                id=incident_id,
                policy_id=policy.id,
                threshold_type=BudgetThreshold.HARD,
                amount_limit=policy.amount,
                amount_observed=observed,
                window_start=self._incident_window(policy, now),
            )
        )
        approval_id = mint_id()
        self._ledger.approvals.request(
            Approval(
                id=approval_id,
                subject_kind=ApprovalSubjectKind.BUDGET_INCIDENT,
                subject_id=incident_id,
                reason=f"{policy.scope_type.value} {policy.scope_id} over budget "
                f"({observed} >= {policy.amount})",
            )
        )
        self._ledger.budget_incidents.attach_approval(incident_id, approval_id)
        self._kill(policy)
        return self._ledger.budget_incidents.get(incident_id)

    def _raise_soft(
        self, policy: BudgetPolicy, observed: int, now: datetime
    ) -> BudgetIncident | None:
        window = self._incident_window(policy, now)
        for incident in self._ledger.budget_incidents.open_for_policy(policy.id):
            if incident.threshold_type is BudgetThreshold.SOFT and incident.window_start == window:
                return None  # already warned for this window
        incident_id = mint_id()
        self._ledger.budget_incidents.open(
            BudgetIncident(
                id=incident_id,
                policy_id=policy.id,
                threshold_type=BudgetThreshold.SOFT,
                amount_limit=policy.amount,
                amount_observed=observed,
                window_start=window,
            )
        )
        return self._ledger.budget_incidents.get(incident_id)

    def _kill(self, policy: BudgetPolicy) -> None:
        scope = None if policy.scope_type is BudgetScope.COMPANY else policy.scope_id
        self._ledger.runs.cancel_running(employee_id=scope)
        self._ledger.wakes.drop_queued(employee_id=scope)

    def _is_paused(self, policy: BudgetPolicy) -> bool:
        return self._open_hard_incident(policy.id) is not None

    def _is_over(self, policy: BudgetPolicy, now: datetime) -> bool:
        return policy.hard_stop_enabled and self._observed_spend(policy, now) >= policy.amount

    def _open_hard_incident(self, policy_id: str) -> BudgetIncident | None:
        for incident in self._ledger.budget_incidents.open_for_policy(policy_id):
            if incident.threshold_type is BudgetThreshold.HARD:
                return incident
        return None

    def _observed_spend(self, policy: BudgetPolicy, now: datetime) -> int:
        start = window_start(BudgetWindow(policy.window_kind), now)
        if policy.scope_type is BudgetScope.EMPLOYEE:
            return self._ledger.cost_events.spent_cents(policy.scope_id, since=start)
        return self._ledger.cost_events.total_spent_cents(since=start)

    def _incident_window(self, policy: BudgetPolicy, now: datetime) -> datetime:
        start = window_start(BudgetWindow(policy.window_kind), now)
        return start if start is not None else _EPOCH

    def _require_policy(self, policy_id: str) -> BudgetPolicy:
        policy = self._ledger.budget_policies.get(policy_id)
        if policy is None:
            raise KeyError(policy_id)
        return policy


__all__ = ["BlockReason", "BudgetEnforcer"]
