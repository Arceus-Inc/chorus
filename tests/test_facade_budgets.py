"""The ``org.budgets`` group (spec 14 §5.2) — set caps, raise_/dismiss after a breach."""

from __future__ import annotations

import pytest

from chorus.budgets import BudgetWindow
from chorus.facade import Caps, Chorus
from chorus.ledger import BudgetScope, Ledger
from chorus.observability import EventBus, LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: Ledger) -> Chorus:
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
        company_id="acme",
    )


def test_set_creates_an_employee_cap() -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="moe", name="Moe", role="engineer"))
        policy = _chorus(ledger).budgets.set(BudgetScope.EMPLOYEE, "moe", 5000)
        assert policy.scope_type is BudgetScope.EMPLOYEE
        assert policy.scope_id == "moe"
        assert policy.amount == 5000
        assert ledger.budget_policies.by_scope(BudgetScope.EMPLOYEE, "moe")[0].amount == 5000
    finally:
        ledger.close()


def test_set_twice_updates_the_same_policy() -> None:
    ledger = open_test_ledger()
    try:
        budgets = _chorus(ledger).budgets
        first = budgets.set(BudgetScope.COMPANY, "acme", 1000)
        second = budgets.set(BudgetScope.COMPANY, "acme", 9000, window=BudgetWindow.MONTHLY)
        assert first.id == second.id  # same scope/window → one policy, updated
        assert second.amount == 9000
        assert len(ledger.budget_policies.all()) == 1
    finally:
        ledger.close()
