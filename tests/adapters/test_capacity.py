"""Observed profession capacity derived from the Chorus ledger."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from dream.contracts.delegation import CapacityPort, ProfessionCapacity

from chorus.adapters import CapacityAdapter
from chorus.ledger import (
    BudgetPolicy,
    BudgetScope,
    CostEvent,
    Ledger,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee, EmployeeStatus

_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


@pytest.fixture
def ledger() -> Iterator[Ledger]:
    store = open_test_ledger()
    try:
        yield store
    finally:
        store.close()


def _employee(
    ledger: Ledger,
    employee_id: str,
    profession: str,
    *,
    status: EmployeeStatus = EmployeeStatus.IDLE,
) -> None:
    ledger.employees.create(
        Employee(id=employee_id, name=employee_id.title(), role=profession, status=status)
    )


def _budget(ledger: Ledger, employee_id: str, *, amount: int, spent: int = 0) -> None:
    ledger.budget_policies.create(
        BudgetPolicy(
            id=uid(f"budget-{employee_id}"),
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=employee_id,
            amount=amount,
        )
    )
    if spent:
        ledger.cost_events.record(
            CostEvent(
                id=uid(f"spend-{employee_id}"),
                employee_id=employee_id,
                provider="test",
                model="test",
                cost_cents=spent,
                occurred_at=_NOW,
            )
        )


def test_snapshot_matches_manual_profession_counts(ledger: Ledger) -> None:
    _employee(ledger, uid("eng-a"), "engineer")
    _employee(ledger, uid("eng-b"), "engineer")
    _employee(ledger, "design-a", "designer", status=EmployeeStatus.PAUSED)
    _budget(ledger, uid("eng-a"), amount=1_000, spent=200)
    _budget(ledger, uid("eng-b"), amount=500, spent=500)

    ledger.tasks.submit(
        Task(
            id=uid("task-running"),
            intent="Run",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id=uid("eng-a"),
        )
    )
    ledger.tasks.submit(
        Task(
            id=uid("task-blocked"),
            intent="Blocked",
            status=TaskStatus.BLOCKED,
            assignee_employee_id=uid("eng-b"),
        )
    )
    ledger.tasks.submit(
        Task(
            id=uid("task-done"),
            intent="Done",
            status=TaskStatus.DONE,
            assignee_employee_id=uid("eng-a"),
        )
    )
    ledger.runs.create(
        Run(
            id=uid("run-a"),
            employee_id=uid("eng-a"),
            task_id=uid("task-running"),
            status=RunStatus.RUNNING,
        )
    )
    ledger.wakes.enqueue(Wake(id=uid("wake-a"), employee_id=uid("eng-a"), reason=WakeReason.MANUAL))
    ledger.wakes.enqueue(Wake(id=uid("wake-b"), employee_id=uid("eng-b"), reason=WakeReason.MANUAL))

    adapter = CapacityAdapter(ledger, company_id="company", clock=lambda: _NOW)

    assert isinstance(adapter, CapacityPort)
    assert adapter.snapshot() == (
        ProfessionCapacity(
            profession="designer",
            eligible=0,
            running=0,
            assigned_nonterminal=0,
            queued_wakes=0,
            budget_blocked=0,
            budget_headroom_cents=None,
        ),
        ProfessionCapacity(
            profession="engineer",
            eligible=1,
            running=1,
            assigned_nonterminal=2,
            queued_wakes=2,
            budget_blocked=1,
            budget_headroom_cents=800,
        ),
    )


def test_unbounded_employee_makes_profession_headroom_unbounded(
    ledger: Ledger,
) -> None:
    _employee(ledger, uid("eng-a"), "engineer")
    _employee(ledger, uid("eng-b"), "engineer")
    _budget(ledger, uid("eng-a"), amount=1_000)

    snapshot = CapacityAdapter(ledger, company_id="company", clock=lambda: _NOW).snapshot()

    assert snapshot[0].budget_headroom_cents is None


def test_terminal_tasks_and_finished_runs_are_not_live_capacity(
    ledger: Ledger,
) -> None:
    _employee(ledger, uid("eng-a"), "engineer")
    ledger.tasks.submit(
        Task(
            id=uid("task-done"),
            intent="Done",
            status=TaskStatus.DONE,
            assignee_employee_id=uid("eng-a"),
        )
    )
    ledger.runs.create(
        Run(
            id=uid("run-done"),
            employee_id=uid("eng-a"),
            task_id=uid("task-done"),
            status=RunStatus.SUCCEEDED,
        )
    )

    capacity = CapacityAdapter(ledger, company_id="company", clock=lambda: _NOW).snapshot()[0]

    assert capacity.running == 0
    assert capacity.assigned_nonterminal == 0
