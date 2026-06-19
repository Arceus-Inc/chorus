"""revise_dod — the manager-authorized DoD revision path (§1 DoD revisability), tighten side.

A tighten by the assignee's manager applies immediately and is audited; a non-manager is rejected; a
no-op is rejected; and a revision never disturbs an already-recorded verdict (the in-flight invariant).
The loosen branch only stages the proposal here — Slice 4 opens its §5 gate.
"""

from __future__ import annotations

import pytest

from chorus.ledger import ActivityVerb, ApprovalAction, DodStatus, SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task
from chorus.lifecycle._revise_dod import (
    NoRevision,
    RevisionAuthorityError,
    revise_dod,
)
from chorus.outcomes import RevisionDirection, Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _task_with_manager(ledger: SqliteLedger, verifier: Verifier) -> None:
    ledger.employees.create(Employee(id="moe", name="moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="ada", role="engineer", reports_to="moe"))
    ledger.tasks.submit(Task(id="t1", intent="ship", status=TaskStatus.IN_PROGRESS))
    assign_task(ledger, "t1", "ada")
    ledger.dod.create("t1", verifier)


def test_manager_tighten_applies_immediately(ledger: SqliteLedger) -> None:
    _task_with_manager(ledger, Verifier.command("pytest"))

    outcome = revise_dod(
        ledger, task_id="t1", new_verifier=Verifier.command("pytest && ruff check"), revised_by="moe"
    )

    assert outcome.direction is RevisionDirection.TIGHTEN and outcome.applied is True
    dod = ledger.dod.get_for_task("t1")
    assert dod is not None and dod.revision == 2
    assert ledger.dod.verifier_for_task("t1").verification_steps()[0].command == "pytest && ruff check"  # type: ignore[union-attr]
    verbs = [a.verb for a in ledger.activity.by_subject("task", "t1")]
    assert ActivityVerb.DOD_REVISED in verbs


def test_non_manager_cannot_revise(ledger: SqliteLedger) -> None:
    _task_with_manager(ledger, Verifier.command("pytest"))
    with pytest.raises(RevisionAuthorityError):
        revise_dod(
            ledger, task_id="t1", new_verifier=Verifier.command("pytest && ruff check"),
            revised_by="ada",  # the worker cannot tighten its own gate
        )


def test_no_change_is_rejected(ledger: SqliteLedger) -> None:
    _task_with_manager(ledger, Verifier.command("pytest"))
    with pytest.raises(NoRevision):
        revise_dod(ledger, task_id="t1", new_verifier=Verifier.command("pytest"), revised_by="moe")


def test_tighten_does_not_rejudge_a_recorded_verdict(ledger: SqliteLedger) -> None:
    _task_with_manager(ledger, Verifier.command("pytest"))
    dod = ledger.dod.get_for_task("t1")
    assert dod is not None
    ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={"ok": True})

    revise_dod(
        ledger, task_id="t1", new_verifier=Verifier.command("pytest && ruff check"), revised_by="moe"
    )

    after = ledger.dod.get_for_task("t1")
    assert after is not None and after.verdict == {"ok": True}  # the in-flight invariant


def test_loosen_stages_the_proposal_and_opens_a_gate(ledger: SqliteLedger) -> None:
    # a loosen stages the proposal (old DoD stays in force) and opens a §5 loosen_dod gate.
    _task_with_manager(ledger, Verifier.command("pytest && ruff check"))

    outcome = revise_dod(
        ledger, task_id="t1", new_verifier=Verifier.command("pytest"), revised_by="moe"
    )

    assert outcome.direction is RevisionDirection.LOOSEN and outcome.applied is False
    assert outcome.approval_id is not None  # the loosen_dod gate
    dod = ledger.dod.get_for_task("t1")
    assert dod is not None and dod.proposed_revision is not None
    assert dod.revision == 1  # not bumped — the loosen is not applied yet
    # the in-force DoD is still the stricter one (both conjuncts).
    steps = ledger.dod.verifier_for_task("t1").verification_steps()  # type: ignore[union-attr]
    assert steps[0].command == "pytest && ruff check"
    assert [a.action for a in ledger.approvals.pending()] == [ApprovalAction.LOOSEN_DOD]
