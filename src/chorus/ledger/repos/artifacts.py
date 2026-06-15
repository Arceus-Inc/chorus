"""ArtifactRepo — the landed outcomes of a task (spec 01 Cluster F ``artifact``)."""

from __future__ import annotations

import sqlite3

from chorus.ledger._models import Artifact, ArtifactType
from chorus.ledger.repos._base import dumps, loads, utcnow_iso


class ArtifactRepo:
    """Create + list ``artifact`` rows."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, artifact: Artifact) -> Artifact:
        now = utcnow_iso()
        self._conn.execute(
            "INSERT INTO artifact (id, task_id, type, provider, external_id, url, review_state, "
            "health_status, is_primary, resource_ref, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.id,
                artifact.task_id,
                artifact.type.value,
                artifact.provider,
                artifact.external_id,
                artifact.url,
                artifact.review_state,
                artifact.health_status,
                1 if artifact.is_primary else 0,
                dumps(artifact.resource_ref) if artifact.resource_ref is not None else None,
                now,
                now,
            ),
        )
        self._conn.commit()
        return artifact

    def list_for_task(self, task_id: str) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM artifact WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        return [_row_to_artifact(row) for row in rows]


def _row_to_artifact(row: sqlite3.Row) -> Artifact:
    return Artifact(
        id=row["id"],
        task_id=row["task_id"],
        type=ArtifactType(row["type"]),
        provider=row["provider"],
        external_id=row["external_id"],
        url=row["url"],
        review_state=row["review_state"],
        health_status=row["health_status"],
        is_primary=bool(row["is_primary"]),
        resource_ref=loads(row["resource_ref"]),
    )
