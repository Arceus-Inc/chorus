"""ArtifactRevisionRepo — immutable artifact history (spec 01 Cluster F ``artifact_revision``).

``record`` appends the next monotonic revision for an artifact (computed in-tx as ``MAX(revision)+1``
scoped to the artifact); rows are never mutated. A revision is the authorized snapshot
``decomposition_claim`` points at, so its id is stable and ``(artifact_id, revision)`` is unique.
"""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import ArtifactRevision
from chorus.ledger.repos._base import dumps, from_iso, loads, utcnow_iso


class ArtifactRevisionRepo:
    """Append + read ``artifact_revision`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def record(self, revision: ArtifactRevision) -> ArtifactRevision:
        """Append the next revision for the artifact; the assigned number is returned."""
        now = utcnow_iso()
        row = self._conn.execute(
            "SELECT COALESCE(MAX(revision), 0) + 1 AS next FROM artifact_revision "
            "WHERE artifact_id = ?",
            (revision.artifact_id,),
        ).fetchone()
        next_revision = int(row["next"])
        self._conn.execute(
            "INSERT INTO artifact_revision (id, artifact_id, revision, resource_ref, summary, "
            "created_by_run_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                revision.id,
                revision.artifact_id,
                next_revision,
                dumps(revision.resource_ref) if revision.resource_ref is not None else None,
                revision.summary,
                revision.created_by_run_id,
                now,
            ),
        )
        self._conn.commit()
        recorded = self.get(revision.id)
        assert recorded is not None  # just inserted in this transaction
        return recorded

    def get(self, revision_id: str) -> ArtifactRevision | None:
        row = self._conn.execute(
            "SELECT * FROM artifact_revision WHERE id = ?", (revision_id,)
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def latest(self, artifact_id: str) -> ArtifactRevision | None:
        """The highest revision recorded for an artifact, or ``None`` if it has no history."""
        row = self._conn.execute(
            "SELECT * FROM artifact_revision WHERE artifact_id = ? ORDER BY revision DESC LIMIT 1",
            (artifact_id,),
        ).fetchone()
        return _row_to_revision(row) if row is not None else None

    def list(self, artifact_id: str) -> list[ArtifactRevision]:
        """An artifact's full revision history, oldest first."""
        rows = self._conn.execute(
            "SELECT * FROM artifact_revision WHERE artifact_id = ? ORDER BY revision",
            (artifact_id,),
        ).fetchall()
        return [_row_to_revision(row) for row in rows]


def _row_to_revision(row: sqlite3.Row) -> ArtifactRevision:
    return ArtifactRevision(
        id=row["id"],
        artifact_id=row["artifact_id"],
        revision=row["revision"],
        resource_ref=loads(row["resource_ref"]),
        summary=row["summary"],
        created_by_run_id=row["created_by_run_id"],
        created_at=from_iso(row["created_at"]),
    )
