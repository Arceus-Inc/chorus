"""Decomposition — exact-once manager fan-out (spec 02 §4).

``decompose`` is the orchestration over spec 01's durable ``decomposition_claim`` +
``create_child`` primitives: open-or-resume a claim keyed on
``(source_task_id, accepted_plan_revision_id)``, create each child one-per-transaction
(``parent_id`` set, goal inherited, ``request_depth`` bumped), wire a *gating* child as a
first-class ``task_dependency`` of the parent, then seal the claim. A run that dies
mid-fan-out resumes from the same fingerprint and reuses the partial result — never
restarts, never double-fans-out.
"""

from __future__ import annotations

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    DecompositionStatus,
    DodStatus,
    Goal,
    OriginKind,
    WakeReason,
)
from chorus.lifecycle import ChildSpec, decompose
from chorus.workforce import Employee

REV = "rev_1"  # the accepted-plan-revision id, backed by a real artifact revision on the source


@pytest.fixture
def emp(ledger: SqliteLedger) -> Employee:
    return ledger.employees.create(Employee(id="emp_1", name="alice", role="engineer"))


@pytest.fixture
def goal(ledger: SqliteLedger) -> Goal:
    return ledger.goals.create(Goal(id="g1", title="ship the thing"))


@pytest.fixture
def source(ledger: SqliteLedger, emp: Employee, goal: Goal) -> Task:
    """The task being split, plus its accepted plan revision (``REV``) for the claim FK."""
    task = ledger.tasks.submit(
        Task(
            id="src",
            intent="big thing",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="emp_1",
            goal_id="g1",
            depth=1,
            request_depth=2,
        )
    )
    ledger.artifacts.create(Artifact(id="art_src", task_id="src", type=ArtifactType.DOC))
    ledger.artifact_revisions.record(
        ArtifactRevision(id=REV, artifact_id="art_src", resource_ref={"plan": "v1"})
    )
    return task


def _child(task_id: str) -> Task:
    return Task(
        id=task_id,
        intent=f"part {task_id}",
        status=TaskStatus.TODO,
        assignee_employee_id="emp_1",
        origin_kind=OriginKind.DECOMPOSITION,
    )


def test_decompose_creates_children_with_inherited_structure(
    ledger: SqliteLedger, source: Task
) -> None:
    decompose(
        ledger,
        source_task_id=source.id,
        accepted_plan_revision_id=REV,
        children=[ChildSpec(_child("c1")), ChildSpec(_child("c2"))],
    )
    c1 = ledger.tasks.get("c1")
    c2 = ledger.tasks.get("c2")
    assert c1 is not None and c2 is not None
    for child in (c1, c2):
        assert child.parent_id == "src"  # structure
        assert child.goal_id == "g1"  # inherited goal
        assert child.request_depth == 3  # bumped from source's 2
        assert child.depth == 2  # bumped from source's 1


def test_gating_child_becomes_a_first_class_dependency(
    ledger: SqliteLedger, source: Task
) -> None:
    decompose(
        ledger,
        source_task_id=source.id,
        accepted_plan_revision_id=REV,
        children=[ChildSpec(_child("c1"), gates_parent=True), ChildSpec(_child("c2"))],
    )
    # parent-waits-on-child is a blocker, not parent_id (spec 02 §4.3).
    assert ledger.dependencies.blockers("src") == ["c1"]
    assert ledger.dependencies.unresolved_blockers("src") == ["c1"]


def test_claim_completes_after_fan_out(ledger: SqliteLedger, source: Task) -> None:
    claim = decompose(
        ledger,
        source_task_id=source.id,
        accepted_plan_revision_id=REV,
        children=[ChildSpec(_child("c1")), ChildSpec(_child("c2"))],
    )
    assert claim.status is DecompositionStatus.COMPLETED
    assert claim.child_task_ids == ["c1", "c2"]


def test_resume_reuses_partial_result_no_duplicate_children(
    ledger: SqliteLedger, source: Task
) -> None:
    specs = [ChildSpec(_child("c1"), gates_parent=True), ChildSpec(_child("c2"))]
    first = decompose(
        ledger, source_task_id=source.id, accepted_plan_revision_id=REV, children=specs
    )
    # A retry against the SAME accepted plan revision resumes the same claim, no double fan-out.
    second = decompose(
        ledger, source_task_id=source.id, accepted_plan_revision_id=REV, children=specs
    )
    assert second.id == first.id  # exact-once: one claim per (source, revision)
    assert second.child_task_ids == ["c1", "c2"]  # not duplicated
    assert ledger.dependencies.blockers("src") == ["c1"]  # dependency add is idempotent


def test_unknown_source_raises(ledger: SqliteLedger, source: Task) -> None:
    with pytest.raises(KeyError):
        decompose(
            ledger,
            source_task_id="nope",
            accepted_plan_revision_id=REV,
            children=[ChildSpec(_child("c1"))],
        )


def test_completing_gating_children_fires_children_done_to_parent(
    ledger: SqliteLedger, source: Task
) -> None:
    # End-to-end wiring: decompose sets parent_id so finalize_beat's last-child rollup fires.
    decompose(
        ledger,
        source_task_id=source.id,
        accepted_plan_revision_id=REV,
        children=[ChildSpec(_child("c1")), ChildSpec(_child("c2"))],
    )
    ledger.finalize_beat(task_id="c1", run_id="r1", dod_status=DodStatus.PASSED)
    fired = ledger.finalize_beat(task_id="c2", run_id="r2", dod_status=DodStatus.PASSED)
    reasons = {w.reason for w in fired}
    assert WakeReason.CHILDREN_DONE in reasons
    parent_wakes = [w for w in fired if w.payload.get("task_id") == "src"]
    assert parent_wakes  # the parent's assignee is woken
