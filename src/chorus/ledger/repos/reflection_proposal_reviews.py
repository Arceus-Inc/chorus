"""Append-only final human decisions for reflection proposals."""

from __future__ import annotations

from chorus.ledger._models import ReflectionProposalReview, ReflectionProposalVerdict
from chorus.ledger.repos._base import (
    LedgerConnection,
    LedgerRow,
    from_iso,
    require_persisted,
    utcnow_iso,
)


class ReflectionProposalReviewRepo:
    """Record and discover one final human verdict per proposal revision."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn = conn

    def record(self, review: ReflectionProposalReview) -> ReflectionProposalReview:
        self._conn.execute(
            "INSERT INTO reflection_proposal_review "
            "(id, proposal_artifact_revision_id, verdict, reviewer_user_id, reason, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                review.id,
                review.proposal_artifact_revision_id,
                review.verdict.value,
                review.reviewer_user_id,
                review.reason,
                utcnow_iso(),
            ),
        )
        self._conn.commit()
        return require_persisted(self.get(review.id), review.id)

    def get(self, review_id: str) -> ReflectionProposalReview | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_proposal_review WHERE id = ?", (review_id,)
        ).fetchone()
        return _row_to_review(row) if row is not None else None

    def for_proposal(self, artifact_revision_id: str) -> ReflectionProposalReview | None:
        row = self._conn.execute(
            "SELECT * FROM reflection_proposal_review "
            "WHERE proposal_artifact_revision_id = ?",
            (artifact_revision_id,),
        ).fetchone()
        return _row_to_review(row) if row is not None else None

    def accepted(self, artifact_revision_id: str) -> ReflectionProposalReview | None:
        review = self.for_proposal(artifact_revision_id)
        if review is None or review.verdict is not ReflectionProposalVerdict.ACCEPTED:
            return None
        return review


def _row_to_review(row: LedgerRow) -> ReflectionProposalReview:
    return ReflectionProposalReview(
        id=row["id"],
        proposal_artifact_revision_id=row["proposal_artifact_revision_id"],
        verdict=ReflectionProposalVerdict(row["verdict"]),
        reviewer_user_id=row["reviewer_user_id"],
        reason=row["reason"],
        created_at=from_iso(row["created_at"]),
    )


__all__ = ["ReflectionProposalReviewRepo"]
