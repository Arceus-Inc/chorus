"""``org.budgets`` — token-salary caps and incident resolution (spec 14 §5.2, spec 04 §3).

``set`` a cap for a scope; when a hard breach pauses the scope, ``raise_`` lifts the cap above the
observed spend and resumes, or ``dismiss_incident`` declines (the scope stays paused). Resume/dismiss
run through the tested :class:`BudgetEnforcer` (atomic).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from chorus.budgets import BudgetEnforcer, BudgetWindow
from chorus.ledger import BudgetPolicy, BudgetScope, SqliteLedger

_DEFAULT_WARN_PERCENT = 80


class BudgetsFacade:
    """The ``org.budgets`` surface — set / raise_ / dismiss_incident."""

    def __init__(self, ledger: SqliteLedger, *, company_id: str) -> None:
        self._ledger = ledger
        self._enforcer = BudgetEnforcer(ledger, company_id=company_id)

    def set(
        self,
        scope: BudgetScope,
        scope_id: str,
        amount_cents: int,
        *,
        warn_percent: int = _DEFAULT_WARN_PERCENT,
        window: BudgetWindow = BudgetWindow.MONTHLY,
    ) -> BudgetPolicy:
        """Create or update the cap for a scope/metric/window (one policy per scope/window)."""
        existing = self._ledger.budget_policies.find(
            scope_type=scope, scope_id=scope_id, window_kind=window.value
        )
        if existing is not None:
            self._ledger.budget_policies.set_amount(existing.id, amount_cents)
            updated = self._ledger.budget_policies.get(existing.id)
            assert updated is not None  # just updated in this transaction
            return updated
        return self._ledger.budget_policies.create(
            BudgetPolicy(
                id=f"bp_{uuid.uuid4().hex[:12]}",
                scope_type=scope,
                scope_id=scope_id,
                amount=amount_cents,
                warn_percent=warn_percent,
                window_kind=window.value,
            )
        )

    def raise_(self, policy_id: str, new_amount_cents: int, *, by: str) -> None:
        """Raise the cap above observed spend and clear the hard incident — the resume path.

        ``raise`` is a Python keyword, so the verb is ``raise_``. Raises ``ValueError`` if
        ``new_amount_cents`` does not exceed the live observed spend (it would just re-trip the gate)."""
        self._enforcer.raise_budget_and_resume(
            policy_id, new_amount_cents, now=datetime.now(UTC), decided_by_user_id=by
        )

    def dismiss_incident(self, incident_id: str, *, by: str) -> None:
        """Decline to resume — deny the approval; the incident stays open so the scope stays paused."""
        self._enforcer.dismiss(incident_id, decided_by_user_id=by)


__all__ = ["BudgetsFacade"]
