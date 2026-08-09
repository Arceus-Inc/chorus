"""Immutable rollout candidates and their append-only promotion decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class RolloutStage(StrEnum):
    """The promotion stage a recorded decision applies to."""

    CANARY = "canary"
    FULL = "full"


class RolloutStatus(StrEnum):
    """The terminal status valid for a rollout stage."""

    COMPLETED = "completed"
    PROMOTED = "promoted"


class ReplayRegression(StrEnum):
    """The highest replay regression observed for a promotion decision."""

    NONE = "none"
    NON_CRITICAL = "non_critical"
    CRITICAL = "critical"


@dataclass(frozen=True)
class PromotionGates:
    """The human-review and replay gates captured for a full promotion."""

    approval_id: str
    reviewer_user_id: str
    replay_regression: ReplayRegression

    def __post_init__(self) -> None:
        if not self.approval_id.strip():
            raise ValueError("promotion approval id must not be blank")
        if not self.reviewer_user_id.strip():
            raise ValueError("promotion reviewer user id must not be blank")


@dataclass(frozen=True)
class Rollout:
    """An immutable candidate revision with one pinned eval run and its exact evidence."""

    id: str
    skill_revision_id: str
    eval_suite_id: str
    eval_run_id: str
    evidence_artifact_revision_ids: tuple[str, ...]
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.id, "rollout id"),
            (self.skill_revision_id, "rollout skill revision id"),
            (self.eval_suite_id, "rollout eval suite id"),
            (self.eval_run_id, "rollout eval run id"),
        ):
            if not value.strip():
                raise ValueError(f"{label} must not be blank")
        if not self.evidence_artifact_revision_ids:
            raise ValueError("rollout evidence artifact revision ids must not be empty")
        if any(not evidence_id.strip() for evidence_id in self.evidence_artifact_revision_ids):
            raise ValueError("rollout evidence artifact revision ids must not be blank")
        if len(self.evidence_artifact_revision_ids) != len(
            set(self.evidence_artifact_revision_ids)
        ):
            raise ValueError("rollout evidence artifact revision ids must not contain duplicates")


@dataclass(frozen=True)
class RolloutDecision:
    """A terminal, append-only canary completion or full-promotion decision."""

    id: str
    rollout_id: str
    stage: RolloutStage
    status: RolloutStatus
    gates: PromotionGates | None = None
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("rollout decision id must not be blank")
        if not self.rollout_id.strip():
            raise ValueError("rollout decision rollout id must not be blank")
        if self.stage is RolloutStage.CANARY:
            if self.status is not RolloutStatus.COMPLETED or self.gates is not None:
                raise ValueError("canary rollout decision must be completed without gates")
        elif self.status is not RolloutStatus.PROMOTED or self.gates is None:
            raise ValueError("full rollout decision must be promoted with gates")


__all__ = [
    "PromotionGates",
    "ReplayRegression",
    "Rollout",
    "RolloutDecision",
    "RolloutStage",
    "RolloutStatus",
]
