"""Immutable, reproducible evaluation-run records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from chorus.ledger._models._agent_config_revisions import AgentConfigRevisionRef


@dataclass(frozen=True)
class EvalInputSnapshot:
    """The exact text supplied to the evaluated agent."""

    text: str


@dataclass(frozen=True)
class EvalOutputSnapshot:
    """The exact text emitted by the evaluated agent."""

    text: str


@dataclass(frozen=True)
class EvalRunUsage:
    """Token and billed usage captured with one evaluation run."""

    input_tokens: int
    output_tokens: int
    cost_usd: Decimal

    def __post_init__(self) -> None:
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("eval run token usage must be nonnegative")
        if not self.cost_usd.is_finite() or self.cost_usd < 0:
            raise ValueError("eval run cost usage must be finite and nonnegative")


class EvalRunStatus(StrEnum):
    """The terminal outcome captured by an immutable evaluation record."""

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class EvalRun:
    """A complete, immutable record of one execution of a revision-pinned eval suite."""

    id: str
    eval_suite_id: str
    skill_revision_id: str
    agent_config_revision: AgentConfigRevisionRef
    provider: str
    model: str
    input_snapshot: EvalInputSnapshot
    output_snapshot: EvalOutputSnapshot
    usage: EvalRunUsage
    artifact_revision_ids: tuple[str, ...]
    status: EvalRunStatus
    started_at: datetime
    completed_at: datetime
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        required_values = (
            (self.id, "eval run id"),
            (self.eval_suite_id, "eval suite id"),
            (self.skill_revision_id, "skill revision id"),
            (self.provider, "provider"),
            (self.model, "model"),
        )
        for value, label in required_values:
            if not value.strip():
                raise ValueError(f"{label} must not be blank")
        if any(
            not artifact_revision_id.strip() for artifact_revision_id in self.artifact_revision_ids
        ):
            raise ValueError("eval run artifact revision ids must not be blank")
        if len(self.artifact_revision_ids) != len(set(self.artifact_revision_ids)):
            raise ValueError("eval run artifact_revision_ids must not contain duplicates")
        if self.completed_at < self.started_at:
            raise ValueError("eval run completed_at must not precede started_at")


__all__ = [
    "AgentConfigRevisionRef",
    "EvalInputSnapshot",
    "EvalOutputSnapshot",
    "EvalRun",
    "EvalRunStatus",
    "EvalRunUsage",
]
