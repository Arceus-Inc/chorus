"""submit_verdict — the Reviewer's verdict move exposed as a dream tool (M3 load-bearing Reviewer)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger, Run, RunStatus, Task, TaskStatus
from chorus.ledger._models import DodStatus
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_tools import SubmitVerdictTool

pytestmark = pytest.mark.integration

_RUN = uid("run_reviewer_1")


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _seed(ledger: Ledger, working_dir: Path) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="pm"))
    ledger.employees.create(Employee(id=uid("rev"), name="Rob", role="reviewer"))
    ledger.tasks.submit(
        Task(
            id=uid("spec"),
            intent="write the spec",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
        )
    )
    ledger.dod.create(
        uid("spec"), Verifier.agent_review(rubric="complete?", artifact_class=uid("spec"))
    )
    ledger.runs.create(
        Run(id=_RUN, employee_id=uid("rev"), task_id=uid("spec"), status=RunStatus.RUNNING)
    )
    # the reviewer beat reads its identity from the worker's worktree (where the kernel drops it)
    BeatContext(task_id=uid("spec"), run_id=_RUN, employee_id=uid("rev")).write(working_dir)


def test_submit_verdict_approve_records_passed(ledger: Ledger, tmp_path: Path) -> None:
    _seed(ledger, tmp_path)
    result = asyncio.run(
        SubmitVerdictTool(ledger).execute(
            {"approve": True, "feedback": "meets the rubric"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False and result.structured["approved"] is True
    dod = ledger.dod.get_for_task(uid("spec"))
    assert dod is not None and dod.status is DodStatus.PASSED


def test_submit_verdict_block_records_failed(ledger: Ledger, tmp_path: Path) -> None:
    _seed(ledger, tmp_path)
    result = asyncio.run(
        SubmitVerdictTool(ledger).execute(
            {"approve": False, "feedback": "section 3 missing"}, _ctx(tmp_path)
        )
    )
    assert result.is_error is False and result.structured["approved"] is False
    dod = ledger.dod.get_for_task(uid("spec"))
    assert dod is not None and dod.status is DodStatus.FAILED


def test_submit_verdict_refuses_self_review(ledger: Ledger, tmp_path: Path) -> None:
    ledger.employees.create(Employee(id=uid("rev"), name="Rob", role="reviewer"))
    ledger.tasks.submit(
        Task(
            id=uid("spec"),
            intent="x",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id=uid("rev"),
        )
    )
    ledger.dod.create(uid("spec"), Verifier.agent_review(artifact_class=uid("spec")))
    ledger.runs.create(
        Run(id=_RUN, employee_id=uid("rev"), task_id=uid("spec"), status=RunStatus.RUNNING)
    )
    BeatContext(task_id=uid("spec"), run_id=_RUN, employee_id=uid("rev")).write(tmp_path)
    result = asyncio.run(
        SubmitVerdictTool(ledger).execute({"approve": True, "feedback": "lgtm"}, _ctx(tmp_path))
    )
    assert result.is_error is True and result.structured["self_review"] is True
