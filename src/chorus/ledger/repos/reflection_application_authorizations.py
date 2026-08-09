"""Accepted reflection proposal handoffs to separate queued runs."""

from __future__ import annotations

from chorus.ledger._models import ReflectionApplicationAuthorization
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class ReflectionApplicationAuthorizationRepo:
    """Issue one append-only application authority per proposal and per run."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def issue(
        self, authorization: ReflectionApplicationAuthorization
    ) -> ReflectionApplicationAuthorization:
        review = self._conn.execute(
            "SELECT rp.source_run_id, review.verdict, review.reviewer_user_id "
            "FROM reflection_proposal rp "
            "JOIN reflection_proposal_review review "
            "ON review.proposal_artifact_revision_id = rp.artifact_revision_id "
            "WHERE rp.artifact_revision_id = ? AND review.id = ?",
            (authorization.proposal_artifact_revision_id, authorization.review_id),
        ).fetchone()
        if (
            review is None
            or review["source_run_id"] != authorization.proposal_source_run_id
            or review["verdict"] != "accepted"
            or review["reviewer_user_id"] != authorization.authorized_by_user_id
        ):
            raise ValueError("reflection application requires the proposal's accepted human review")

        application_run = self._conn.execute(
            "SELECT status FROM run WHERE id = ?", (authorization.application_run_id,)
        ).fetchone()
        if application_run is not None and application_run["status"] != "queued":
            raise ValueError("reflection application run must still be queued")

        self._conn.execute(
            "INSERT INTO reflection_application_authorization "
            "(id, proposal_artifact_revision_id, review_id, proposal_source_run_id, "
            "application_run_id, authorized_by_user_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                authorization.id,
                authorization.proposal_artifact_revision_id,
                authorization.review_id,
                authorization.proposal_source_run_id,
                authorization.application_run_id,
                authorization.authorized_by_user_id,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(authorization.id), authorization.id)

    def get(self, authorization_id: str) -> ReflectionApplicationAuthorization | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_application_authorization WHERE id = ?",
            (authorization_id,),
        ).fetchone()
        return _row_to_authorization(row) if row is not None else None

    def for_proposal(
        self, artifact_revision_id: str
    ) -> ReflectionApplicationAuthorization | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_application_authorization "
            "WHERE proposal_artifact_revision_id = ?",
            (artifact_revision_id,),
        ).fetchone()
        return _row_to_authorization(row) if row is not None else None

    def for_run(self, run_id: str) -> ReflectionApplicationAuthorization | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_application_authorization WHERE application_run_id = ?",
            (run_id,),
        ).fetchone()
        return _row_to_authorization(row) if row is not None else None


def _row_to_authorization(row: LedgerRow) -> ReflectionApplicationAuthorization:
    return ReflectionApplicationAuthorization(
        id=row["id"],
        proposal_artifact_revision_id=row["proposal_artifact_revision_id"],
        review_id=row["review_id"],
        proposal_source_run_id=row["proposal_source_run_id"],
        application_run_id=row["application_run_id"],
        authorized_by_user_id=row["authorized_by_user_id"],
        created_at=from_iso(row["created_at"]),
    )


__all__ = ["ReflectionApplicationAuthorizationRepo"]
