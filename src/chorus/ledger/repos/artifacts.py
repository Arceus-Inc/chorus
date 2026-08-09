"""ArtifactRepo — the landed outcomes of a task (spec 01 Cluster F ``artifact``)."""

from __future__ import annotations

from chorus.ledger._models import Artifact, ArtifactType
from chorus.ledger.repos._base import LedgerConnection, LedgerRow, dumps, loads, utcnow_iso


class ArtifactRepo:
    """Create + list ``artifact`` rows."""

    def __init__(self, conn: LedgerConnection) -> None:
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
                artifact.is_primary,
                dumps(artifact.resource_ref) if artifact.resource_ref is not None else None,
                now,
                now,
            ),
        )
        self._conn.commit()
        return artifact

    def list_recent(self, *, limit: int) -> list[Artifact]:
        """The company's landed outcomes, newest first — the product's artifacts index."""
        rows = self._conn.execute(
            "SELECT * FROM artifact ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [_row_to_artifact(row) for row in rows]

    def get(self, artifact_id: str) -> Artifact | None:
        row = self._conn.execute("SELECT * FROM artifact WHERE id = ?", (artifact_id,)).fetchone()
        return _row_to_artifact(row) if row is not None else None

    def list_for_task(self, task_id: str) -> list[Artifact]:
        rows = self._conn.execute(
            "SELECT * FROM artifact WHERE task_id = ? ORDER BY created_at", (task_id,)
        ).fetchall()
        return [_row_to_artifact(row) for row in rows]

    def has_pending_primary_non_verdict(self, task_id: str) -> bool:
        return _latest_pending_primary_non_verdict_for_task(self._conn, task_id) is not None

    def mark_latest_pending_primary_non_verdict_verified(self, task_id: str) -> Artifact | None:
        artifact = _latest_pending_primary_non_verdict_for_task(self._conn, task_id)
        if artifact is None:
            return None
        self._conn.execute(
            "UPDATE artifact SET review_state = ?, updated_at = ? WHERE id = ?",
            ("verified", utcnow_iso(), artifact.id),
        )
        self._conn.commit()
        return self.get(artifact.id)


def _row_to_artifact(row: LedgerRow) -> Artifact:
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


def _latest_pending_primary_non_verdict_for_task(
    conn: LedgerConnection, task_id: str
) -> Artifact | None:
    row = conn.execute(
        "SELECT * FROM artifact WHERE task_id = ? AND is_primary = ? AND type <> ? AND review_state = ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1",
        (task_id, True, ArtifactType.VERDICT.value, "pending"),
    ).fetchone()
    return _row_to_artifact(row) if row is not None else None
