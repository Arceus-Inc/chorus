"""Facade transactions + beat-end finalize (spec 01 Cluster F, spec 02 §4, spec 03).

Covers the cross-aggregate atomic operations the per-aggregate repos can't express alone:
``ledger.transaction()`` (batch many repo writes into one commit/rollback), ``finalize_beat`` (write
the dod verdict + derive ``task.status='done'`` + enqueue the downstream wakes the *next* beat picks
up), and ``create_child`` (decomposition child + claim append, atomically).
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    DecompositionClaim,
    DodStatus,
    Ledger,
    Run,
    Task,
    TaskStatus,
    WakeReason,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _emp(ledger: Ledger, eid: str) -> str:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))
    return eid


# --- transaction() -------------------------------------------------------------------------------


def test_transaction_commits_all_writes(ledger: Ledger) -> None:
    with ledger.transaction():
        ledger.tasks.submit(Task(id=uid("t1"), intent=uid("a")))
        ledger.tasks.submit(Task(id=uid("t2"), intent=uid("b")))
    assert ledger.tasks.get(uid("t1")) is not None
    assert ledger.tasks.get(uid("t2")) is not None


def test_transaction_rolls_back_on_error(ledger: Ledger) -> None:
    with pytest.raises(RuntimeError):
        with ledger.transaction():
            ledger.tasks.submit(Task(id=uid("t1"), intent=uid("a")))
            raise RuntimeError("boom")
    assert ledger.tasks.get(uid("t1")) is None  # nothing persisted


def test_caught_inner_error_still_rolls_back_outer(ledger: Ledger) -> None:
    # a nested block that fails (and whose error the caller swallows) must still abort the outer
    with ledger.transaction():
        try:
            with ledger.transaction():
                ledger.tasks.submit(Task(id=uid("t1"), intent=uid("a")))
                raise RuntimeError("inner boom")
        except RuntimeError:
            pass
        ledger.tasks.submit(Task(id=uid("t2"), intent=uid("b")))
    assert ledger.tasks.get(uid("t1")) is None
    assert ledger.tasks.get(uid("t2")) is None  # outer committed nothing — the abort latched


def _task_with_dod(ledger: Ledger, tid: str = uid("t1")) -> str:
    _emp(ledger, uid("e1"))
    ledger.tasks.submit(Task(id=tid, intent="x", assignee_employee_id=uid("e1")))
    ledger.dod.create(tid, Verifier.command("pytest -q"))
    ledger.runs.create(
        Run(id=uid("r1"), employee_id=uid("e1"), task_id=tid)
    )  # dod.verified_by_run_id FK
    return tid


def test_finalize_passed_marks_done_and_records_verdict(ledger: Ledger) -> None:
    _task_with_dod(ledger)
    ledger.finalize_beat(
        task_id=uid("t1"), run_id=uid("r1"), dod_status=DodStatus.PASSED, verdict={"score": 1}
    )
    task = ledger.tasks.get(uid("t1"))
    dod = ledger.dod.get_for_task(uid("t1"))
    assert task is not None and task.status is TaskStatus.DONE
    assert task.completed_at is not None
    assert dod is not None and dod.status is DodStatus.PASSED
    assert dod.verdict == {"score": 1}
    assert dod.verified_by_run_id == uid("r1")


def test_finalize_without_a_run_marks_done(ledger: Ledger) -> None:
    # the human-approval path lands a verdict with no beat run behind it (spec 04 §5)
    _emp(ledger, uid("e1"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", assignee_employee_id=uid("e1")))
    ledger.dod.create(uid("t1"), Verifier.human_approval())
    ledger.finalize_beat(task_id=uid("t1"), run_id=None, dod_status=DodStatus.PASSED)
    task = ledger.tasks.get(uid("t1"))
    dod = ledger.dod.get_for_task(uid("t1"))
    assert task is not None and task.status is TaskStatus.DONE
    assert dod is not None and dod.status is DodStatus.PASSED and dod.verified_by_run_id is None


def test_finalize_failed_records_verdict_but_not_done(ledger: Ledger) -> None:
    _task_with_dod(ledger)
    ledger.finalize_beat(task_id=uid("t1"), run_id=uid("r1"), dod_status=DodStatus.FAILED)
    task = ledger.tasks.get(uid("t1"))
    dod = ledger.dod.get_for_task(uid("t1"))
    assert task is not None and task.status is not TaskStatus.DONE
    assert task.completed_at is None
    assert dod is not None and dod.status is DodStatus.FAILED


# --- finalize_beat: downstream wakes (the "picked up next beat" hand-off) -------------------------


def test_finalize_fires_deps_resolved_for_unblocked_dependent(ledger: Ledger) -> None:
    _emp(ledger, uid("e2"))
    ledger.tasks.submit(Task(id=uid("a"), intent="blocker"))
    ledger.tasks.submit(
        Task(
            id=uid("b"), intent="dependent", status=TaskStatus.TODO, assignee_employee_id=uid("e2")
        )
    )
    ledger.dependencies.add(uid("b"), uid("a"))  # b depends on a
    fired = ledger.finalize_beat(task_id=uid("a"), run_id=uid("r"), dod_status=DodStatus.PASSED)
    assert [(w.reason, w.employee_id, w.payload["task_id"]) for w in fired] == [
        (WakeReason.DEPS_RESOLVED, uid("e2"), uid("b"))
    ]
    # b is now eligible for the next beat to pick up
    assert uid("b") in [t.id for t in ledger.tasks.list_eligible(limit=10)]


def test_finalize_fires_children_done_only_when_last_child_lands(ledger: Ledger) -> None:
    _emp(ledger, uid("e1"))
    ledger.tasks.submit(Task(id=uid("p"), intent="parent", assignee_employee_id=uid("e1")))
    ledger.tasks.submit(Task(id=uid("c1"), intent="child 1", parent_id=uid("p")))
    ledger.tasks.submit(Task(id=uid("c2"), intent="child 2", parent_id=uid("p")))
    first = ledger.finalize_beat(task_id=uid("c1"), run_id=uid("r"), dod_status=DodStatus.PASSED)
    assert first == []  # c2 still open -> no children_done yet
    last = ledger.finalize_beat(task_id=uid("c2"), run_id=uid("r"), dod_status=DodStatus.PASSED)
    assert [(w.reason, w.employee_id, w.payload["task_id"]) for w in last] == [
        (WakeReason.CHILDREN_DONE, uid("e1"), uid("p"))
    ]


# --- create_child: atomic decomposition fan-out --------------------------------------------------


def _claim(ledger: Ledger) -> str:
    ledger.tasks.submit(Task(id=uid("src"), intent="decompose"))
    ledger.artifacts.create(Artifact(id=uid("plan"), task_id=uid("src"), type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev1"), artifact_id=uid("plan")))
    ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc1"), source_task_id=uid("src"), accepted_plan_revision_id=uid("rev1")
        )
    )
    return uid("dc1")


def test_create_child_persists_task_and_records_on_claim(ledger: Ledger) -> None:
    _claim(ledger)
    claim = ledger.create_child(
        uid("dc1"), Task(id=uid("child1"), intent="sub", parent_id=uid("src"))
    )
    assert claim.child_task_ids == [uid("child1")]
    assert ledger.tasks.get(uid("child1")) is not None


def test_create_child_is_idempotent_on_retry(ledger: Ledger) -> None:
    _claim(ledger)
    ledger.create_child(uid("dc1"), Task(id=uid("child1"), intent="sub", parent_id=uid("src")))
    # a resumed fan-out re-creates the same child id -> no duplicate insert, no error
    claim = ledger.create_child(
        uid("dc1"), Task(id=uid("child1"), intent="sub", parent_id=uid("src"))
    )
    assert claim.child_task_ids == [uid("child1")]


def test_create_child_unknown_claim_raises(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("src"), intent="x"))
    with pytest.raises(KeyError):
        ledger.create_child(
            uid("ghost"), Task(id=uid("child1"), intent="sub", parent_id=uid("src"))
        )
    assert ledger.tasks.get(uid("child1")) is None  # rolled back


def test_create_child_on_sealed_claim_rolls_back(ledger: Ledger) -> None:
    _claim(ledger)
    ledger.decomposition_claims.complete(uid("dc1"))
    with pytest.raises(ValueError, match="not in_flight"):
        ledger.create_child(uid("dc1"), Task(id=uid("child1"), intent="sub", parent_id=uid("src")))
    # the child task insert was rolled back with the rejected claim append
    assert ledger.tasks.get(uid("child1")) is None
