"""Final human review decisions for immutable reflection proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReflectionProposalVerdict(StrEnum):
    """The two final outcomes of a human proposal review."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"


@dataclass(frozen=True)
class ReflectionProposalReview:
    """One final human verdict pinned to an exact proposal artifact revision."""

    id: str
    proposal_artifact_revision_id: str
    verdict: ReflectionProposalVerdict
    reviewer_user_id: str
    reason: str
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.verdict, ReflectionProposalVerdict):
            raise ValueError("reflection proposal verdict must be a ReflectionProposalVerdict")
        for value, label in (
            (self.id, "review id"),
            (self.proposal_artifact_revision_id, "proposal artifact revision id"),
            (self.reviewer_user_id, "reviewer user id"),
            (self.reason, "review reason"),
        ):
            if not value.strip():
                raise ValueError(f"reflection proposal {label} must not be blank")


__all__ = ["ReflectionProposalReview", "ReflectionProposalVerdict"]
