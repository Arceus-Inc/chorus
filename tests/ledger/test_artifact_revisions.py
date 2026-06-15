"""ArtifactRevisionRepo — immutable artifact history (spec 01 Cluster F ``artifact_revision``).

Each ``record`` appends the next monotonic revision for an artifact; rows are never mutated. A
revision is *the thing decomposition is authorized against* — ``decomposition_claim`` FKs its
``accepted_plan_revision_id`` here, so the id must be stable and the (artifact, revision) pair unique.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger import Artifact, ArtifactRevision, ArtifactType, Run, SqliteLedger, Task
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _artifact(ledger: SqliteLedger, aid: str = "art1") -> str:
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.artifacts.create(Artifact(id=aid, task_id="t1", type=ArtifactType.DOC))
    return aid


def _run(ledger: SqliteLedger, run_id: str = "run1") -> str:
    ledger.employees.create(Employee(id="e1", name="e1", role="engineer"))
    ledger.runs.create(Run(id=run_id, employee_id="e1", task_id="t1"))
    return run_id


def test_record_assigns_monotonic_revisions(ledger: SqliteLedger) -> None:
    aid = _artifact(ledger)
    r1 = ledger.artifact_revisions.record(
        ArtifactRevision(id="rev1", artifact_id=aid, resource_ref={"plan": "v1"})
    )
    r2 = ledger.artifact_revisions.record(
        ArtifactRevision(id="rev2", artifact_id=aid, resource_ref={"plan": "v2"})
    )
    assert r1.revision == 1
    assert r2.revision == 2


def test_get_reads_back(ledger: SqliteLedger) -> None:
    aid = _artifact(ledger)
    run_id = _run(ledger)
    ledger.artifact_revisions.record(
        ArtifactRevision(
            id="rev1", artifact_id=aid, resource_ref={"plan": "v1"}, created_by_run_id=run_id
        )
    )
    got = ledger.artifact_revisions.get("rev1")
    assert got is not None
    assert got.artifact_id == aid
    assert got.revision == 1
    assert got.resource_ref == {"plan": "v1"}
    assert got.created_by_run_id == "run1"
    assert got.created_at is not None


def test_latest_returns_highest_revision(ledger: SqliteLedger) -> None:
    aid = _artifact(ledger)
    ledger.artifact_revisions.record(ArtifactRevision(id="rev1", artifact_id=aid))
    ledger.artifact_revisions.record(ArtifactRevision(id="rev2", artifact_id=aid))
    latest = ledger.artifact_revisions.latest(aid)
    assert latest is not None
    assert latest.id == "rev2"
    assert latest.revision == 2


def test_latest_is_none_when_no_revisions(ledger: SqliteLedger) -> None:
    aid = _artifact(ledger)
    assert ledger.artifact_revisions.latest(aid) is None


def test_list_returns_history_oldest_first(ledger: SqliteLedger) -> None:
    aid = _artifact(ledger)
    ledger.artifact_revisions.record(ArtifactRevision(id="rev1", artifact_id=aid))
    ledger.artifact_revisions.record(ArtifactRevision(id="rev2", artifact_id=aid))
    assert [r.id for r in ledger.artifact_revisions.list(aid)] == ["rev1", "rev2"]


def test_revisions_are_per_artifact(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.artifacts.create(Artifact(id="artA", task_id="t1", type=ArtifactType.DOC))
    ledger.artifacts.create(Artifact(id="artB", task_id="t1", type=ArtifactType.DOC))
    ledger.artifact_revisions.record(ArtifactRevision(id="rA1", artifact_id="artA"))
    rB1 = ledger.artifact_revisions.record(ArtifactRevision(id="rB1", artifact_id="artB"))
    # each artifact's revision sequence is independent
    assert rB1.revision == 1


def test_unknown_artifact_rejected(ledger: SqliteLedger) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        ledger.artifact_revisions.record(ArtifactRevision(id="rev1", artifact_id="ghost"))
