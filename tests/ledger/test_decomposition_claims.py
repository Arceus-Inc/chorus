"""DecompositionClaimRepo — exact-once fan-out (spec 01 Cluster A ``decomposition_claim``).

The manager-splits-work primitive; the most important crash-safety object after the locks. A claim
is durable *before* fan-out starts, accumulates ``child_task_ids`` one-per-tx while underway, and is
durable after. Re-reading the same accepted plan revision can't authorize a second child tree — the
``(source_task_id, accepted_plan_revision_id)`` pair is unique, so a retry resumes the same claim and
reuses the children it already created.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    DecompositionClaim,
    DecompositionStatus,
    Ledger,
    LedgerIntegrityError,
    Run,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _plan_revision(ledger: Ledger, *, source: str = uid("t1"), rev_id: str = uid("rev1")) -> str:
    ledger.tasks.submit(Task(id=source, intent="decompose me"))
    ledger.artifacts.create(Artifact(id=uid("plan"), task_id=source, type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=rev_id, artifact_id=uid("plan")))
    # owner_run_id is FK→run, so the owning run must exist
    ledger.employees.create(Employee(id=uid("e1"), name=uid("e1"), role="engineer"))
    ledger.runs.create(Run(id=uid("run1"), employee_id=uid("e1"), task_id=source))
    return rev_id


def test_open_and_get(ledger: Ledger) -> None:
    rev = _plan_revision(ledger)
    opened = ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc1"),
            source_task_id=uid("t1"),
            accepted_plan_revision_id=rev,
            owner_run_id=uid("run1"),
            request_fingerprint="fp1",
            requested_children=[{"intent": "a"}, {"intent": "b"}],
        )
    )
    got = ledger.decomposition_claims.get(opened.id)
    assert got is not None
    assert got.status is DecompositionStatus.IN_FLIGHT
    assert got.source_task_id == uid("t1")
    assert got.accepted_plan_revision_id == rev
    assert got.owner_run_id == uid("run1")
    assert got.requested_children == [{"intent": "a"}, {"intent": "b"}]
    assert got.child_task_ids == []
    assert got.completed_at is None


def test_same_source_and_revision_is_exact_once(ledger: Ledger) -> None:
    rev = _plan_revision(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(id=uid("dc1"), source_task_id=uid("t1"), accepted_plan_revision_id=rev)
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.decomposition_claims.open(
            DecompositionClaim(
                id=uid("dc2"), source_task_id=uid("t1"), accepted_plan_revision_id=rev
            )
        )


def test_by_source_revision_is_the_resume_lookup(ledger: Ledger) -> None:
    rev = _plan_revision(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(id=uid("dc1"), source_task_id=uid("t1"), accepted_plan_revision_id=rev)
    )
    found = ledger.decomposition_claims.by_source_revision(uid("t1"), rev)
    assert found is not None
    assert found.id == uid("dc1")
    assert ledger.decomposition_claims.by_source_revision(uid("t1"), uid("other")) is None


def test_add_child_accumulates_durably(ledger: Ledger) -> None:
    rev = _plan_revision(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(id=uid("dc1"), source_task_id=uid("t1"), accepted_plan_revision_id=rev)
    )
    ledger.decomposition_claims.add_child(uid("dc1"), "child1")
    updated = ledger.decomposition_claims.add_child(uid("dc1"), "child2")
    assert updated.child_task_ids == ["child1", "child2"]


def test_add_child_is_idempotent(ledger: Ledger) -> None:
    # a retry that re-creates the same child must not duplicate the partial result
    rev = _plan_revision(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(id=uid("dc1"), source_task_id=uid("t1"), accepted_plan_revision_id=rev)
    )
    ledger.decomposition_claims.add_child(uid("dc1"), "child1")
    updated = ledger.decomposition_claims.add_child(uid("dc1"), "child1")
    assert updated.child_task_ids == ["child1"]


def test_add_child_on_unknown_claim_raises(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        ledger.decomposition_claims.add_child(uid("ghost"), "child1")


def test_complete_marks_done(ledger: Ledger) -> None:
    rev = _plan_revision(ledger)
    ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc1"),
            source_task_id=uid("t1"),
            accepted_plan_revision_id=rev,
            owner_run_id=uid("run1"),
        )
    )
    ledger.decomposition_claims.complete(uid("dc1"))
    got = ledger.decomposition_claims.get(uid("dc1"))
    assert got is not None
    assert got.status is DecompositionStatus.COMPLETED
    assert got.completed_at is not None


def test_active_for_owner_lists_in_flight_only(ledger: Ledger) -> None:
    rev1 = _plan_revision(ledger, source=uid("t1"), rev_id=uid("rev1"))
    ledger.tasks.submit(Task(id=uid("t2"), intent="decompose me too"))
    ledger.artifacts.create(Artifact(id=uid("plan2"), task_id=uid("t2"), type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev2"), artifact_id=uid("plan2")))
    ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc1"),
            source_task_id=uid("t1"),
            accepted_plan_revision_id=rev1,
            owner_run_id=uid("run1"),
        )
    )
    ledger.decomposition_claims.open(
        DecompositionClaim(
            id=uid("dc2"),
            source_task_id=uid("t2"),
            accepted_plan_revision_id=uid("rev2"),
            owner_run_id=uid("run1"),
        )
    )
    ledger.decomposition_claims.complete(uid("dc1"))
    active = ledger.decomposition_claims.active_for_owner(uid("run1"))
    assert [c.id for c in active] == [uid("dc2")]
