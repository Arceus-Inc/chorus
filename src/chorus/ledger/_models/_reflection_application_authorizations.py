"""Separate-run authority for applying an accepted reflection proposal."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ReflectionApplicationAuthorization:
    """A single-use handoff from an accepted proposal to one queued application run."""

    id: str
    proposal_artifact_revision_id: str
    review_id: str
    proposal_source_run_id: str
    application_run_id: str
    authorized_by_user_id: str
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "authorization id"),
            (self.proposal_artifact_revision_id, "proposal artifact revision id"),
            (self.review_id, "review id"),
            (self.proposal_source_run_id, "proposal source run id"),
            (self.application_run_id, "application run id"),
            (self.authorized_by_user_id, "authorized by user id"),
        ):
            if not value.strip():
                raise ValueError(f"reflection application {label} must not be blank")
        if self.proposal_source_run_id == self.application_run_id:
            raise ValueError("reflection proposal application requires a separate run")


__all__ = ["ReflectionApplicationAuthorization"]
