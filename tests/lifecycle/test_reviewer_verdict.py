"""CapabilityService.record_verdict — the Reviewer's ledger-mutating capability (M3, spec 06 §4).

The dream-free seam the reviewer beat's ``submit_verdict`` tool calls. The reviewer's approve/block
verdict IS the work task's ``agent_review`` DoD verdict: approve records ``PASSED``, block records
``FAILED``. A reviewer may not verify its own work, and only an ``agent_review`` DoD is reviewable.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.ledger._models import ActivityVerb, DodStatus
from chorus.lifecycle._capability import CapabilityService
from chorus.outcomes import Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_REVIEW_RUN = "run_reviewer_1"


def _reviewed_task(ledger: SqliteLedger, *, author: str = "ada") -> CapabilityService:
    """A work task assigned to ``author`` with a pending agent_review DoD, plus a hired reviewer."""
    ledger.employees.create(Employee(id="rev", name="Rob", role="reviewer"))
    if author != "rev":
        ledger.employees.create(Employee(id=author, name="Ada", role="pm"))
    ledger.tasks.submit(
        Task(
            id="spec",
            intent="write the spec",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id=author,
        )
    )
    ledger.dod.create(
        "spec", Verifier.agent_review(rubric="is it complete?", artifact_class="spec")
    )
    ledger.runs.create(
        Run(id=_REVIEW_RUN, employee_id="rev", task_id="spec", status=RunStatus.RUNNING)
    )
    return CapabilityService(ledger)


def test_approve_records_a_passed_verdict(ledger: SqliteLedger) -> None:
    svc = _reviewed_task(ledger)
    result = svc.record_verdict(
        task_id="spec", run_id=_REVIEW_RUN, reviewer_id="rev", approve=True, feedback="solid"
    )
    assert result.recorded is True and result.approved is True
    dod = ledger.dod.get_for_task("spec")
    assert dod is not None and dod.status is DodStatus.PASSED
    assert dod.verdict == {"approve": True, "feedback": "solid", "reviewer": "rev"}
    audit = [
        a
        for a in ledger.activity.by_subject("task", "spec")
        if a.verb is ActivityVerb.REVIEW_VERDICT
    ]
    assert len(audit) == 1 and audit[0].actor_employee_id == "rev"


def test_block_records_a_failed_verdict(ledger: SqliteLedger) -> None:
    svc = _reviewed_task(ledger)
    result = svc.record_verdict(
        task_id="spec",
        run_id=_REVIEW_RUN,
        reviewer_id="rev",
        approve=False,
        feedback="missing section 3",
    )
    assert result.recorded is True and result.approved is False
    dod = ledger.dod.get_for_task("spec")
    assert dod is not None and dod.status is DodStatus.FAILED
    assert dod.verdict is not None and dod.verdict["feedback"] == "missing section 3"


def test_reviewer_cannot_verify_its_own_work(ledger: SqliteLedger) -> None:
    # the author is also (wrongly) the reviewer — self-review is refused, nothing recorded
    svc = _reviewed_task(ledger, author="rev")
    result = svc.record_verdict(
        task_id="spec", run_id=_REVIEW_RUN, reviewer_id="rev", approve=True, feedback="lgtm"
    )
    assert result.self_review is True and result.recorded is False
    dod = ledger.dod.get_for_task("spec")
    assert dod is not None and dod.status is DodStatus.PENDING  # untouched


def test_verdict_records_the_discovered_verify_command(ledger: SqliteLedger) -> None:
    # For a reviewed build the reviewer reports the project's verify command; the kernel runs it later.
    ledger.employees.create(Employee(id="rev", name="Rob", role="reviewer"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(id="code", intent="build", status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada")
    )
    ledger.dod.create("code", Verifier.reviewed_build(artifact_class="pr"))
    ledger.runs.create(
        Run(id=_REVIEW_RUN, employee_id="rev", task_id="code", status=RunStatus.RUNNING)
    )

    result = CapabilityService(ledger).record_verdict(
        task_id="code",
        run_id=_REVIEW_RUN,
        reviewer_id="rev",
        approve=True,
        feedback="clean",
        verify_command="npm ci && npm test",
    )
    assert result.recorded is True and result.approved is True
    dod = ledger.dod.get_for_task("code")
    assert dod is not None and dod.verdict == {
        "approve": True,
        "feedback": "clean",
        "reviewer": "rev",
        "verify_command": "npm ci && npm test",
    }


def test_a_non_agent_review_dod_is_not_reviewable(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.employees.create(Employee(id="rev", name="Rob", role="reviewer"))
    ledger.tasks.submit(
        Task(
            id="code", intent="ship code", status=TaskStatus.IN_PROGRESS, assignee_employee_id="ada"
        )
    )
    ledger.dod.create("code", Verifier.command("pytest -q"))  # a command DoD, not a judgment gate
    ledger.runs.create(
        Run(id=_REVIEW_RUN, employee_id="rev", task_id="code", status=RunStatus.RUNNING)
    )
    result = CapabilityService(ledger).record_verdict(
        task_id="code", run_id=_REVIEW_RUN, reviewer_id="rev", approve=True, feedback="x"
    )
    assert result.not_reviewable is True and result.recorded is False
