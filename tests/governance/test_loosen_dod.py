"""loosen_dod — lowering a DoD requires §5 sign-off (§1 DoD revisability), end to end.

A manager loosens a task's DoD: the proposal is staged behind a ``loosen_dod`` gate while the old,
stricter DoD stays in force. Approve promotes the looser verifier (+ bumps revision); deny/revise drop
it and keep the stricter gate. Driven through the real resolver + revise_dod.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.governance import ApprovalDecision, GovernanceResolver
from chorus.ledger import ApprovalAction, SqliteLedger, Task, TaskStatus
from chorus.lifecycle import assign_task, revise_dod
from chorus.outcomes import DoDKind, Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)
_USER = "chair"


def _loosened_with_open_gate(ledger: SqliteLedger) -> str:
    """A manager loosens t1's DoD (reviewed_build → command); returns the open gate id."""
    ledger.employees.create(Employee(id="moe", name="moe", role="engineer"))
    ledger.employees.create(Employee(id="ada", name="ada", role="engineer", reports_to="moe"))
    ledger.tasks.submit(Task(id="t1", intent="ship", status=TaskStatus.IN_PROGRESS))
    assign_task(ledger, "t1", "ada")
    ledger.dod.create("t1", Verifier.reviewed_build())
    outcome = revise_dod(
        ledger, task_id="t1", new_verifier=Verifier.command("pytest"), revised_by="moe"
    )
    assert outcome.approval_id is not None
    return outcome.approval_id


def test_loosen_holds_the_stricter_dod_until_approved(ledger: SqliteLedger) -> None:
    _loosened_with_open_gate(ledger)
    # the old reviewed_build DoD is still in force while the gate is pending.
    assert ledger.dod.verifier_for_task("t1").kind is DoDKind.REVIEWED_BUILD  # type: ignore[union-attr]
    assert [a.action for a in ledger.approvals.pending()] == [ApprovalAction.LOOSEN_DOD]


def test_approve_promotes_the_looser_dod(ledger: SqliteLedger) -> None:
    gate = _loosened_with_open_gate(ledger)

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.APPROVE, decided_by_user_id=_USER, now=_NOW
    )

    dod = ledger.dod.get_for_task("t1")
    assert dod is not None and dod.revision == 2 and dod.proposed_revision is None
    assert (
        ledger.dod.verifier_for_task("t1").kind is DoDKind.COMMAND
    )  # the loosen is in force  # type: ignore[union-attr]


def test_deny_keeps_the_stricter_dod(ledger: SqliteLedger) -> None:
    gate = _loosened_with_open_gate(ledger)

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.DENY, decided_by_user_id=_USER, now=_NOW
    )

    dod = ledger.dod.get_for_task("t1")
    assert (
        dod is not None and dod.revision == 1 and dod.proposed_revision is None
    )  # staging dropped
    assert ledger.dod.verifier_for_task("t1").kind is DoDKind.REVIEWED_BUILD  # type: ignore[union-attr]


def test_revise_withdraws_the_staged_loosen(ledger: SqliteLedger) -> None:
    gate = _loosened_with_open_gate(ledger)

    GovernanceResolver(ledger).resolve(
        gate, decision=ApprovalDecision.REQUEST_REVISION, decided_by_user_id=_USER, now=_NOW
    )

    dod = ledger.dod.get_for_task("t1")
    assert dod is not None and dod.proposed_revision is None
    assert ledger.dod.verifier_for_task("t1").kind is DoDKind.REVIEWED_BUILD  # type: ignore[union-attr]


def test_handler_action_kind() -> None:
    from chorus.governance._actions import LoosenDodAction

    assert LoosenDodAction.action is ApprovalAction.LOOSEN_DOD
