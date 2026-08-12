"""The scheduler stores typed landed carryover independently of Dream sessions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.context import ContextAudience, project_task_context, render_task_context
from chorus.heartbeat import BeatOutcome, Scheduler, Wake, WakeReason
from chorus.ledger import (
    BudgetPolicy,
    BudgetScope,
    CostEvent,
    Ledger,
    LedgerIntegrityError,
    Run,
    RunCarryover,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

_NOW = datetime.fromisoformat("2026-08-09T12:00:00+00:00")


class _Workforce:
    def __init__(self, employee: Employee) -> None:
        self.employee = employee

    def get(self, employee_id: str) -> Employee:
        assert employee_id == self.employee.id
        return self.employee


class _Beat:
    def __init__(self, working_dir: Path) -> None:
        self.working_dir = working_dir

    async def run_task(self, **_: object) -> BeatOutcome:
        return BeatOutcome(
            passed=True,
            summary="implementation landed",
            evaluator_notes=("verification passed",),
        )


async def test_landed_carryover_survives_as_a_typed_task_projection(
    ledger: Ledger, tmp_path: Path
) -> None:
    employee = ledger.employees.create(Employee(id="e1", name="E1", role="backend_engineer"))
    task_id = uid("task")
    run_id = uid("run")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship context", status=TaskStatus.TODO, assignee_employee_id="e1")
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    assert ledger.tasks.checkout(task_id, employee_id="e1", run_id=run_id)
    ledger.wakes.enqueue(
        Wake(
            id=uid("wake"),
            employee_id="e1",
            reason=WakeReason.TASK_ASSIGNED,
            payload={"task_id": task_id},
        )
    )
    (wake,) = ledger.wakes.claim(limit=1)
    todo = "review the migration\n" + "keep every durable TODO line\n" * 300
    (tmp_path / "TODO.md").write_text(todo, encoding="utf-8")

    await Scheduler(ledger=ledger, workforce=_Workforce(employee), beat_runner=_Beat(tmp_path)).run_beat(
        wake, run_id=run_id, now=_NOW
    )

    carryover = ledger.run_carryovers.get(run_id)
    assert carryover is not None
    assert carryover.evaluator_notes == ("verification passed",)
    assert carryover.todo_digest == todo
    reassigned = ledger.employees.create(Employee(id="e2", name="E2", role="backend_engineer"))
    packet = project_task_context(ledger, task_id=task_id, employee=reassigned)
    assert packet.prior_beats[0].run_id == run_id
    assert packet.prior_beats[0].recovery_hint is RecoveryHint.NONE
    assert packet.prior_beats[0].todo_digest == todo


def test_carryover_uses_its_run_for_task_membership_and_rejects_mismatches(ledger: Ledger) -> None:
    employee = ledger.employees.create(Employee(id="e-carry", name="Carry", role="backend_engineer"))
    task = ledger.tasks.submit(Task(id=uid("carry-task"), intent="carry", assignee_employee_id=employee.id))
    other_task = ledger.tasks.submit(
        Task(id=uid("other-task"), intent="other", assignee_employee_id=employee.id)
    )
    run = Run(id=uid("carry-run"), employee_id=employee.id, task_id=task.id, status=RunStatus.FAILED)
    ledger.runs.create(run)
    carryover = RunCarryover(
        run_id=run.id,
        phase=LandedPhase.NEEDS_REWORK,
        recovery_hint=RecoveryHint.REWORK,
        evaluator_notes=("preserve this finding",),
        files_touched=("src/context.py",),
        todo_digest="finish the durable checkpoint",
        summary="review requested",
    )

    assert ledger.run_carryovers.append(carryover) == carryover
    assert ledger.run_carryovers.append(carryover) == carryover
    assert ledger.run_carryovers.for_task(task.id) == [carryover]
    assert ledger.run_carryovers.for_task(other_task.id) == []
    with pytest.raises(LedgerIntegrityError, match="different payload"):
        ledger.run_carryovers.append(
            RunCarryover(
                run_id=run.id,
                phase=LandedPhase.NEEDS_REWORK,
                recovery_hint=RecoveryHint.REWORK,
                evaluator_notes=("different finding",),
                files_touched=("src/context.py",),
                todo_digest="finish the durable checkpoint",
                summary="review requested",
            )
        )
    assert ledger.run_carryovers.get(run.id) == carryover


def test_context_preserves_full_selected_carryover_contract_and_sibling_findings(
    ledger: Ledger,
) -> None:
    employee = ledger.employees.create(Employee(id="e-exact", name="Exact", role="backend_engineer"))
    parent = ledger.tasks.submit(Task(id=uid("parent"), intent="parent objective"))
    failed = ledger.tasks.submit(
        Task(
            id=uid("failed"),
            intent="failed implementation",
            parent_id=parent.id,
            assignee_employee_id=employee.id,
            status=TaskStatus.REJECTED,
        )
    )
    intent = "complete exact context " + "I" * 1_500
    task = ledger.tasks.submit(
        Task(
            id=uid("corrective"),
            intent=intent,
            parent_id=parent.id,
            assignee_employee_id=employee.id,
        )
    )
    command = "pytest " + "C" * 1_500
    ledger.dod.create(task.id, Verifier.command(command))
    run = Run(id=uid("exact-run"), employee_id=employee.id, task_id=task.id, status=RunStatus.FAILED)
    failed_run = Run(
        id=uid("sibling-run"), employee_id=employee.id, task_id=failed.id, status=RunStatus.FAILED
    )
    ledger.runs.create(run)
    ledger.runs.create(failed_run)
    notes = tuple(f"carryover finding {index}: " + "N" * 1_300 for index in range(10))
    files = tuple(f"src/deep/path/file_{index}.py" for index in range(25))
    todo = "\n".join(f"- exact TODO line {index}: " + "T" * 120 for index in range(20))
    summary = "summary: " + "S" * 1_500
    sibling_notes = tuple(f"corrective finding {index}: " + "F" * 1_300 for index in range(10))
    ledger.run_carryovers.append(
        RunCarryover(
            run_id=run.id,
            phase=LandedPhase.NEEDS_REWORK,
            recovery_hint=RecoveryHint.REWORK,
            evaluator_notes=notes,
            files_touched=files,
            todo_digest=todo,
            summary=summary,
        )
    )
    ledger.run_carryovers.append(
        RunCarryover(
            run_id=failed_run.id,
            phase=LandedPhase.TERMINAL_FAIL,
            recovery_hint=RecoveryHint.REWORK,
            evaluator_notes=sibling_notes,
        )
    )

    packet = project_task_context(ledger, task_id=task.id, employee=employee)
    (prior,) = packet.prior_beats
    assert packet.contract.intent == intent
    assert packet.contract.dod[0].detail == f"{command} (timeout 300s)"
    assert prior.evaluator_notes == notes
    assert prior.files_touched == files
    assert prior.todo_digest == todo
    assert prior.summary == summary
    assert packet.sibling_failures[0].notes == sibling_notes

    rendered = render_task_context(packet, ContextAudience.GENERATOR)
    assert notes[-1] in rendered
    assert files[-1] in rendered
    assert todo in rendered
    assert summary in rendered
    assert sibling_notes[-1] in rendered


def test_context_budget_uses_the_monthly_window_and_an_active_policy(ledger: Ledger) -> None:
    employee = ledger.employees.create(
        Employee(id="e-budget", name="Budget", role="backend_engineer", budget_monthly_cents=0)
    )
    task = ledger.tasks.submit(Task(id=uid("budget-task"), intent="budget", assignee_employee_id=employee.id))
    ledger.budget_policies.create(
        BudgetPolicy(
            id=uid("budget-policy"),
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=employee.id,
            amount=100,
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("july"),
            employee_id=employee.id,
            provider="test",
            model="test",
            cost_cents=70,
            occurred_at=datetime.fromisoformat("2026-07-31T23:59:00+00:00"),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("august"),
            employee_id=employee.id,
            provider="test",
            model="test",
            cost_cents=5,
            occurred_at=datetime.fromisoformat("2026-08-01T00:01:00+00:00"),
        )
    )

    packet = project_task_context(
        ledger,
        task_id=task.id,
        employee=employee,
        now=datetime.fromisoformat("2026-08-09T12:00:00+00:00"),
    )

    assert packet.budget.spent_cents == 5
    assert packet.budget.limit_cents == 100
