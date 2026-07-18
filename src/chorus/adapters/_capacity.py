"""Observed profession capacity projected from the Chorus ledger."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from dream.contracts.delegation import ProfessionCapacity

if TYPE_CHECKING:
    from chorus.ledger import Ledger

_TERMINAL_TASK_STATUSES = {"cancelled", "done", "rejected"}


class CapacityAdapter:
    """Implement Dream's capacity port as a read-only ledger snapshot."""

    def __init__(
        self,
        ledger: Ledger,
        *,
        company_id: str,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        from chorus.budgets import BudgetEnforcer
        from chorus.workforce._ledger import LedgerWorkforce

        self._ledger = ledger
        self._workforce = LedgerWorkforce(ledger.employees)
        self._budgets = BudgetEnforcer(ledger, company_id=company_id)
        self._clock = clock or (lambda: datetime.now(UTC))

    def snapshot(self) -> tuple[ProfessionCapacity, ...]:
        """Return stable profession aggregates without reserving or mutating capacity."""
        from chorus.heartbeat._invokability import invokability_block

        now = self._clock()
        employees = self._workforce.list()
        by_id = {employee.id: employee for employee in employees}
        professions = sorted({employee.role for employee in employees})
        running: defaultdict[str, int] = defaultdict(int)
        assigned: defaultdict[str, int] = defaultdict(int)
        queued: defaultdict[str, int] = defaultdict(int)

        for employee_id in self._ledger.runs.running_employee_ids():
            employee = by_id.get(employee_id)
            if employee is not None:
                running[employee.role] += 1
        for task in self._ledger.tasks.all():
            employee = by_id.get(task.assignee_employee_id or "")
            if employee is not None and task.status.value not in _TERMINAL_TASK_STATUSES:
                assigned[employee.role] += 1
        for wake in self._ledger.wakes.queued():
            employee = by_id.get(wake.employee_id)
            if employee is not None:
                queued[employee.role] += 1

        result: list[ProfessionCapacity] = []
        for profession in professions:
            eligible = 0
            budget_blocked = 0
            headrooms: list[int | None] = []
            for employee in employees:
                if employee.role != profession:
                    continue
                if invokability_block(self._workforce, employee.id) is not None:
                    continue
                if self._budgets.invocation_block(employee.id, now=now) is not None:
                    budget_blocked += 1
                    continue
                eligible += 1
                headrooms.append(self._headroom(employee.id, now=now))
            result.append(
                ProfessionCapacity(
                    profession=profession,
                    eligible=eligible,
                    running=running[profession],
                    assigned_nonterminal=assigned[profession],
                    queued_wakes=queued[profession],
                    budget_blocked=budget_blocked,
                    budget_headroom_cents=_sum_headroom(headrooms),
                )
            )
        return tuple(result)

    def _headroom(self, employee_id: str, *, now: datetime) -> int | None:
        from chorus.budgets import BudgetWindow
        from chorus.budgets._window import window_start
        from chorus.ledger import BudgetScope

        policies = [
            policy
            for policy in self._ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, employee_id)
            if policy.metric == "cost_cents"
        ]
        if not policies:
            return None
        return min(
            policy.amount
            - self._ledger.cost_events.spent_cents(
                employee_id,
                since=window_start(BudgetWindow(policy.window_kind), now),
            )
            for policy in policies
        )


def _sum_headroom(headrooms: list[int | None]) -> int | None:
    if not headrooms or any(headroom is None for headroom in headrooms):
        return None
    return sum(headroom for headroom in headrooms if headroom is not None)


__all__ = ["CapacityAdapter"]
