"""ArtifactRepo — the landed outcomes of a task (spec 01 Cluster F ``artifact``)."""

from __future__ import annotations

from chorus.ledger._models import Artifact, ArtifactType
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    dumps,
    from_iso,
    loads,
    utcnow_iso,
)


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
            "SELECT * FROM artifact WHERE task_id = ? ORDER BY created_at, id", (task_id,)
        ).fetchall()
        return [_row_to_artifact(row) for row in rows]

    def latest_primary_non_verdict(self, task_id: str) -> Artifact | None:
        return _latest_primary_non_verdict_for_task(self._conn, task_id)

    def has_pending_primary_non_verdict(self, task_id: str) -> bool:
        return _latest_pending_primary_non_verdict_for_task(self._conn, task_id) is not None

    def mark_latest_pending_primary_non_verdict_verified(self, task_id: str) -> Artifact | None:
        """CAS-stamp the newest pending primary at write time; never rewrite other columns.

        The subquery and ``RETURNING`` are one statement so the stamped row is the newest
        pending primary as of the write, not a previously selected id.
        """
        cursor = self._conn.execute(
            "UPDATE artifact SET review_state = ?, updated_at = ? "
            "WHERE id = ("
            "SELECT id FROM artifact "
            "WHERE task_id = ? AND is_primary = ? AND type <> ? AND review_state = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1"
            ") AND review_state = ? "
            "RETURNING *",
            (
                "verified",
                utcnow_iso(),
                task_id,
                True,
                ArtifactType.VERDICT.value,
                "pending",
                "pending",
            ),
        )
        row = cursor.fetchone()
        self._conn.commit()
        return _row_to_artifact(row) if row is not None else None


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
        created_at=from_iso(row["created_at"]),
    )


def _latest_primary_non_verdict_for_task(conn: LedgerConnection, task_id: str) -> Artifact | None:
    return _fetch_latest_primary_non_verdict(conn, task_id, pending_only=False)


def _latest_pending_primary_non_verdict_for_task(
    conn: LedgerConnection, task_id: str
) -> Artifact | None:
    return _fetch_latest_primary_non_verdict(conn, task_id, pending_only=True)


def _fetch_latest_primary_non_verdict(
    conn: LedgerConnection, task_id: str, *, pending_only: bool
) -> Artifact | None:
    sql = (
        "SELECT * FROM artifact WHERE task_id = ? AND is_primary = ? AND type <> ? "
        "AND review_state = ? ORDER BY created_at DESC, id DESC LIMIT 1"
        if pending_only
        else "SELECT * FROM artifact WHERE task_id = ? AND is_primary = ? AND type <> ? "
        "ORDER BY created_at DESC, id DESC LIMIT 1"
    )
    params: tuple[object, ...] = (
        (task_id, True, ArtifactType.VERDICT.value, "pending")
        if pending_only
        else (task_id, True, ArtifactType.VERDICT.value)
    )
    row = conn.execute(sql, params).fetchone()
    return _row_to_artifact(row) if row is not None else None
