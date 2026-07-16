"""Delegation depth cap — the manager fan-out fails closed at the cap (spec 06 §4).

Every decomposed child inherits ``parent.request_depth + 1``. The cap bounds the manager recursion:
at the cap a decompose creates **no** children, sets the source ``blocked``, and opens a typed
``recovery_action(cause='request_depth_exceeded')`` naming the manager — visible work, never a silent
drop. The check runs *before* the ``decomposition_claim`` opens, so a breach leaves no partial fan-out.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Artifact, ArtifactRevision, ArtifactType, SqliteLedger, Task
from chorus.ledger._models import RecoveryKind, RecoveryStatus, TaskStatus
from chorus.lifecycle import ChildSpec, DepthCapped, Fanned, decompose
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _manager_with_source(ledger: SqliteLedger, *, request_depth: int) -> None:
    ledger.employees.create(Employee(id="mgr", name="m", role="engineer"))
    ledger.tasks.submit(
        Task(id="src", intent="big", assignee_employee_id="mgr", request_depth=request_depth)
    )


def _accepted_plan(ledger: SqliteLedger, *, source_id: str, revision_id: str) -> None:
    """Seed the manager's accepted plan revision the decomposition claim references (spec 02 §4)."""
    ledger.artifacts.create(
        Artifact(id=f"plan_{source_id}", task_id=source_id, type=ArtifactType.DOC)
    )
    ledger.artifact_revisions.record(
        ArtifactRevision(id=revision_id, artifact_id=f"plan_{source_id}")
    )


def test_decompose_under_cap_fans_out(ledger: SqliteLedger) -> None:
    _manager_with_source(ledger, request_depth=0)
    _accepted_plan(ledger, source_id="src", revision_id="rev_1")
    outcome = decompose(
        ledger,
        source_task_id="src",
        accepted_plan_revision_id="rev_1",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
        request_depth_cap=5,
    )
    assert isinstance(outcome, Fanned)
    child = ledger.tasks.get("c1")
    assert child is not None
    assert child.request_depth == 1  # inherited parent + 1


def test_decompose_one_below_cap_is_allowed(ledger: SqliteLedger) -> None:
    # source at depth 4, cap 5 → child lands at depth 5 (== cap) → allowed.
    _manager_with_source(ledger, request_depth=4)
    _accepted_plan(ledger, source_id="src", revision_id="rev_1")
    outcome = decompose(
        ledger,
        source_task_id="src",
        accepted_plan_revision_id="rev_1",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
        request_depth_cap=5,
    )
    assert isinstance(outcome, Fanned)
    assert ledger.tasks.get("c1") is not None


def test_decompose_at_cap_fails_closed(ledger: SqliteLedger) -> None:
    # source at depth 5, cap 5 → child would be depth 6 > cap → refuse.
    _manager_with_source(ledger, request_depth=5)
    outcome = decompose(
        ledger,
        source_task_id="src",
        accepted_plan_revision_id="rev_1",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
        request_depth_cap=5,
    )
    assert isinstance(outcome, DepthCapped)
    assert ledger.tasks.get("c1") is None  # no child created
    assert ledger.tasks.get("src").status is TaskStatus.BLOCKED  # type: ignore[union-attr]


def test_fail_closed_opens_a_typed_recovery_naming_the_manager(ledger: SqliteLedger) -> None:
    _manager_with_source(ledger, request_depth=5)
    outcome = decompose(
        ledger,
        source_task_id="src",
        accepted_plan_revision_id="rev_1",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
        request_depth_cap=5,
    )
    assert isinstance(outcome, DepthCapped)
    recovery = outcome.recovery
    assert recovery.cause == "request_depth_exceeded"
    assert recovery.kind is RecoveryKind.STRANDED
    assert recovery.owner_employee_id == "mgr"
    assert recovery.status is RecoveryStatus.ACTIVE
    assert recovery.evidence["cap"] == 5
    assert ledger.recovery_actions.active_for_source("src") is not None


def test_fail_closed_is_idempotent_on_retry(ledger: SqliteLedger) -> None:
    _manager_with_source(ledger, request_depth=5)
    args = dict(
        source_task_id="src",
        children=[ChildSpec(Task(id="c1", intent="part 1"))],
        request_depth_cap=5,
    )
    first = decompose(ledger, accepted_plan_revision_id="rev_1", **args)  # type: ignore[arg-type]
    second = decompose(ledger, accepted_plan_revision_id="rev_2", **args)  # type: ignore[arg-type]
    assert isinstance(first, DepthCapped) and isinstance(second, DepthCapped)
    assert first.recovery.id == second.recovery.id  # one recovery, not double-opened


def test_decompose_unknown_source_raises(ledger: SqliteLedger) -> None:
    with pytest.raises(KeyError):
        decompose(
            ledger,
            source_task_id="ghost",
            accepted_plan_revision_id="rev_1",
            children=[ChildSpec(Task(id="c1", intent="x"))],
        )
