"""CLI observability surfaces for org and manager scrum packet rollups."""

from __future__ import annotations

import io

from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.workforce import Employee
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY)
    return signal, buffer.getvalue()


def _seed(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(Task(id="M", intent="ship", status=TaskStatus.TODO, assignee_employee_id="mgr"))
    ledger.runs.create(Run(id="run_mgr_1", employee_id="mgr", task_id="M", status=RunStatus.RUNNING))
    CapabilityService(ledger).decompose(
        parent_id="M",
        revision="run_mgr_1",
        children=(
            ChildPlan(label="api", intent="build api", assignee="ada"),
            ChildPlan(label="ui", intent="build ui", assignee="bob", depends_on=("api",)),
        ),
    )


def test_check_org_reports_combined_manager_and_leaf_metrics(ledger: SqliteLedger) -> None:
    _seed(ledger)

    _, out = _run("check org", CliSession(ledger=ledger))

    assert "employees" in out
    assert "managers" in out
    assert "leaves" in out
    assert "decomposition_count" in out
    assert "manager" in out and "completion" in out


def test_check_scrum_reports_one_manager_packet(ledger: SqliteLedger) -> None:
    _seed(ledger)

    _, out = _run("check scrum M", CliSession(ledger=ledger))

    assert "parent_task" in out
    assert "completion_rate" in out
    assert "reassignments" in out
    assert "api" in out and "ui" in out
