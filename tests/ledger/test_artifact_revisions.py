"""ArtifactRevisionRepo — immutable artifact history (spec 01 Cluster F ``artifact_revision``).

Each ``record`` appends the next monotonic revision for an artifact; rows are never mutated. A
revision is *the thing decomposition is authorized against* — ``decomposition_claim`` FKs its
``accepted_plan_revision_id`` here, so the id must be stable and the (artifact, revision) pair unique.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Ledger,
    LedgerIntegrityError,
    Run,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _artifact(ledger: Ledger, aid: str = uid("art1")) -> str:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.artifacts.create(Artifact(id=aid, task_id=uid("t1"), type=ArtifactType.DOC))
    return aid


def _run(ledger: Ledger, run_id: str = uid("run1")) -> str:
    ledger.employees.create(Employee(id=uid("e1"), name=uid("e1"), role="engineer"))
    ledger.runs.create(Run(id=run_id, employee_id=uid("e1"), task_id=uid("t1")))
    return run_id


def test_record_assigns_monotonic_revisions(ledger: Ledger) -> None:
    aid = _artifact(ledger)
    r1 = ledger.artifact_revisions.record(
        ArtifactRevision(id=uid("rev1"), artifact_id=aid, resource_ref={"plan": "v1"})
    )
    r2 = ledger.artifact_revisions.record(
        ArtifactRevision(id=uid("rev2"), artifact_id=aid, resource_ref={"plan": "v2"})
    )
    assert r1.revision == 1
    assert r2.revision == 2


def test_get_reads_back(ledger: Ledger) -> None:
    aid = _artifact(ledger)
    run_id = _run(ledger)
    ledger.artifact_revisions.record(
        ArtifactRevision(
            id=uid("rev1"), artifact_id=aid, resource_ref={"plan": "v1"}, created_by_run_id=run_id
        )
    )
    got = ledger.artifact_revisions.get(uid("rev1"))
    assert got is not None
    assert got.artifact_id == aid
    assert got.revision == 1
    assert got.resource_ref == {"plan": "v1"}
    assert got.created_by_run_id == uid("run1")
    assert got.created_at is not None


def test_latest_returns_highest_revision(ledger: Ledger) -> None:
    aid = _artifact(ledger)
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev1"), artifact_id=aid))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev2"), artifact_id=aid))
    latest = ledger.artifact_revisions.latest(aid)
    assert latest is not None
    assert latest.id == uid("rev2")
    assert latest.revision == 2


def test_latest_is_none_when_no_revisions(ledger: Ledger) -> None:
    aid = _artifact(ledger)
    assert ledger.artifact_revisions.latest(aid) is None


def test_list_returns_history_oldest_first(ledger: Ledger) -> None:
    aid = _artifact(ledger)
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev1"), artifact_id=aid))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev2"), artifact_id=aid))
    assert [r.id for r in ledger.artifact_revisions.list(aid)] == [uid("rev1"), uid("rev2")]


def test_revisions_are_per_artifact(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.artifacts.create(Artifact(id=uid("artA"), task_id=uid("t1"), type=ArtifactType.DOC))
    ledger.artifacts.create(Artifact(id=uid("artB"), task_id=uid("t1"), type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id=uid("rA1"), artifact_id=uid("artA")))
    rB1 = ledger.artifact_revisions.record(ArtifactRevision(id=uid("rB1"), artifact_id=uid("artB")))
    # each artifact's revision sequence is independent
    assert rB1.revision == 1


def test_unknown_artifact_rejected(ledger: Ledger) -> None:
    with pytest.raises(LedgerIntegrityError):
        ledger.artifact_revisions.record(ArtifactRevision(id=uid("rev1"), artifact_id=uid("ghost")))
