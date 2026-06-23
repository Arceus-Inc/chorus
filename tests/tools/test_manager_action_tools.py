"""Manager action tools — bounded integrate-beat moves exposed as dream tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.workforce import Employee
from chorus_tools import AssignTaskTool, SubmitTaskTool

pytestmark = pytest.mark.integration

REV = "run_mgr_integrate_1"

_AUTHORED_AGENTS_MD = (
    "# AGENTS.md\n## Module map\n- `pkg/__init__.py` — entry\n- `pkg/core.py` — Thing\n"
    "## Public API\n- `pkg.Thing`\n## Ownership\n- `pkg/core.py` -> ada\n"
)


def _author_contract(working_dir: Path) -> None:
    # spec 15 §4.1: a FIRST submit_task (parent has no children) is contract-gated like decompose.
    (working_dir / "AGENTS.md").write_text(_AUTHORED_AGENTS_MD, encoding="utf-8")


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _seed(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Mgr", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(Task(id="M", intent="ship it", status=TaskStatus.TODO, assignee_employee_id="mgr"))
    ledger.runs.create(Run(id=REV, employee_id="mgr", task_id="M", status=RunStatus.RUNNING))


def test_submit_task_tool_creates_one_child(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    _author_contract(tmp_path)

    result = asyncio.run(
        SubmitTaskTool(ledger).execute(
            {"label": "fix", "intent": "fix the integration gap", "assignee": "ada"},
            _ctx(tmp_path),
        )
    )

    assert result.is_error is False
    child_id = result.structured["child_id"]
    child = ledger.tasks.get(child_id)
    assert child is not None
    assert child.parent_id == "M"
    assert child.assignee_employee_id == "ada"
    assert ledger.dependencies.unresolved_blockers("M") == [child_id]


def test_submit_task_tool_rejects_non_report(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    _author_contract(tmp_path)

    result = asyncio.run(
        SubmitTaskTool(ledger).execute(
            {"label": "fix", "intent": "fix", "assignee": "eve"},
            _ctx(tmp_path),
        )
    )

    assert result.is_error is True
    assert result.structured["unknown_assignees"] == ["eve"]
    assert ledger.dependencies.unresolved_blockers("M") == []


def test_submit_task_tool_is_contract_gated_on_first_fan_out(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    # spec 15 §4.1: a manager that fans out via submit_task (not decompose) is gated the same way — no
    # authored AGENTS.md → refused, nothing created. Closes the decompose-only bypass.
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)  # no contract authored
    result = asyncio.run(
        SubmitTaskTool(ledger).execute(
            {"label": "fix", "intent": "fix", "assignee": "ada"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is True
    assert result.structured["contract_unauthored"] is True
    assert ledger.dependencies.unresolved_blockers("M") == []


def test_assign_task_tool_routes_existing_child(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)
    _author_contract(tmp_path)
    submit = asyncio.run(
        SubmitTaskTool(ledger).execute(
            {"label": "fix", "intent": "fix", "assignee": "ada"},
            _ctx(tmp_path),
        )
    )

    result = asyncio.run(
        AssignTaskTool(ledger).execute(
            {"task_id": submit.structured["child_id"], "assignee": "bob"},
            _ctx(tmp_path),
        )
    )

    assert result.is_error is False
    assert ledger.tasks.get(submit.structured["child_id"]).assignee_employee_id == "bob"  # type: ignore[union-attr]


def test_assign_task_tool_rejects_non_child(ledger: SqliteLedger, tmp_path: Path) -> None:
    _seed(ledger)
    ledger.tasks.submit(Task(id="outside", intent="outside", status=TaskStatus.TODO, assignee_employee_id="ada"))
    BeatContext(task_id="M", run_id=REV, employee_id="mgr").write(tmp_path)

    result = asyncio.run(
        AssignTaskTool(ledger).execute({"task_id": "outside", "assignee": "bob"}, _ctx(tmp_path))
    )

    assert result.is_error is True
    assert result.structured["not_child"] is True
