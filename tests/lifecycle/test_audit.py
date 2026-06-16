"""Governance audit emission + tier-3 escalation (spec 02 §6, spec 08 §5).

The ``activity`` stream must actually be written by the runtime: decomposition, recovery, and the
disposition escalation each land an immutable governance row. Recovery escalation is also no longer
silent — it leaves the audit trail *and* escalates up the chain of command, and the finish-handoff
wake carries the structured disposition menu.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.ledger import (
    ActivityVerb,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Run,
    RunStatus,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.lifecycle import ChildSpec, DispositionAction, decompose, reconcile_disposition
from chorus.recovery import reconcile
from chorus.workforce import Employee

NOW = datetime(2026, 6, 16, 12, 0, 0, tzinfo=UTC)


def _verbs(ledger: SqliteLedger, task_id: str) -> list[ActivityVerb]:
    return [a.verb for a in ledger.activity.by_subject("task", task_id)]


# -- decomposition audit --------------------------------------------------------------------------


def test_decompose_emits_decomposed_activity(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="m", role="manager"))
    ledger.tasks.submit(Task(id="src", intent="big", assignee_employee_id="mgr"))
    ledger.artifacts.create(Artifact(id="plan", task_id="src", type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id="rev_1", artifact_id="plan"))

    decompose(
        ledger,
        source_task_id="src",
        accepted_plan_revision_id="rev_1",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
    )

    acts = ledger.activity.by_subject("task", "src")
    assert [a.verb for a in acts] == [ActivityVerb.DECOMPOSED]
    assert acts[0].actor_employee_id == "mgr"
    assert acts[0].payload["children"] == ["c1"]


# -- recovery escalation: audit trail + escalate up the chain --------------------------------------


def test_recovery_escalation_audits_and_wakes_manager(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="boss", role="manager"))
    ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(
        Task(id="t1", intent="x", status=TaskStatus.TODO, assignee_employee_id="emp_1")
    )
    ledger.runs.create(Run(id="r1", employee_id="emp_1", task_id="t1", status=RunStatus.FAILED))

    reconcile(ledger, now=NOW)  # tier 1: enqueue one recovery wake
    [recovery_wake] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(recovery_wake.id)  # the employee ran it; still stranded
    reconcile(ledger, now=NOW)  # tier 2/3: escalate

    assert ActivityVerb.RECOVERED in _verbs(ledger, "t1")
    manager_wakes = ledger.wakes.queued(employee_id="mgr")
    assert [w.payload.get("kind") for w in manager_wakes] == ["escalation"]
    assert manager_wakes[0].payload["stranded_owner"] == "emp_1"


def test_recovery_escalation_without_manager_still_audits(ledger: SqliteLedger) -> None:
    # org-root owner has no manager: the activity trail is the visibility, no wake fabricated
    ledger.employees.create(Employee(id="root", name="ceo", role="founder"))
    ledger.tasks.submit(
        Task(id="t1", intent="x", status=TaskStatus.TODO, assignee_employee_id="root")
    )
    ledger.runs.create(Run(id="r1", employee_id="root", task_id="t1", status=RunStatus.FAILED))

    reconcile(ledger, now=NOW)
    [w] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(w.id)
    reconcile(ledger, now=NOW)

    assert ActivityVerb.RECOVERED in _verbs(ledger, "t1")


# -- disposition: handoff menu + escalation audit --------------------------------------------------


def _disposition_setup(ledger: SqliteLedger) -> Task:
    ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))
    task = ledger.tasks.submit(
        Task(id="t1", intent="ship", status=TaskStatus.IN_PROGRESS, assignee_employee_id="emp_1")
    )
    ledger.runs.create(Run(id="r1", employee_id="emp_1", task_id="t1", status=RunStatus.SUCCEEDED))
    return task


def test_finish_handoff_wake_carries_choice_menu(ledger: SqliteLedger) -> None:
    task = _disposition_setup(ledger)
    reconcile_disposition(task, ledger, now=NOW)
    [wake] = ledger.wakes.queued(employee_id="emp_1")
    assert wake.payload["choices"] == ["done", "cancelled", "in_review", "blocked", "delegate"]


def test_disposition_escalation_emits_recovered_activity(ledger: SqliteLedger) -> None:
    task = _disposition_setup(ledger)
    reconcile_disposition(task, ledger, now=NOW)  # enqueue handoff
    [wake] = ledger.wakes.claim(limit=1)
    ledger.wakes.mark_done(wake.id)  # delivered, still stranded
    again = ledger.tasks.get("t1")
    assert again is not None
    result = reconcile_disposition(again, ledger, now=NOW)  # escalate

    assert result.action is DispositionAction.ESCALATED
    assert ActivityVerb.RECOVERED in _verbs(ledger, "t1")


pytestmark = pytest.mark.integration
