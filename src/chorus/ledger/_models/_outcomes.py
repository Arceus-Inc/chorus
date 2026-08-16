"""Outcome row models — DoD, Artifact, and artifact revisions (Cluster D)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from chorus.ledger._models._enums import (
    ArtifactType,
    DodStatus,
)


@dataclass(frozen=True)
class Dod:
    """Definition-of-done + verification record, 1:1 with a task (spec 01 Cluster F).

    The ``dod`` row is the authoritative verdict: ``task.status`` is derived from
    ``status`` (``done`` iff ``passed``); ``run.outcome`` is the raw input it is
    computed from (spec 01 Cluster F invariant).
    """

    id: str
    task_id: str
    kind: str
    spec: dict[str, object] = field(default_factory=dict)
    artifact_class: str | None = None
    revision: int = 1
    status: DodStatus = DodStatus.PENDING
    verdict: dict[str, object] | None = None
    verified_by_run_id: str | None = None
    proposed_revision: dict[str, object] | None = None  # a loosen staged for §5 approval (§1)


@dataclass(frozen=True)
class Artifact:
    """A landed outcome — a PR, doc, or finding (spec 01 Cluster F)."""

    id: str
    task_id: str
    type: ArtifactType
    provider: str | None = None
    external_id: str | None = None
    url: str | None = None
    review_state: str | None = None
    health_status: str | None = None
    is_primary: bool = False
    resource_ref: dict[str, object] | None = None
    created_at: datetime | None = None


@dataclass(frozen=True)
class ArtifactRevision:
    """Immutable artifact history (spec 01 Cluster F ``artifact_revision``).

    Each row is a frozen snapshot of an :class:`Artifact` at one ``revision`` (monotonic per
    artifact, assigned by the repo on record). A revision is *the thing decomposition is authorized
    against* — :class:`DecompositionClaim` FKs its ``accepted_plan_revision_id`` here.
    """

    id: str
    artifact_id: str
    revision: int = 0
    resource_ref: dict[str, object] | None = None
    summary: str | None = None
    created_by_run_id: str | None = None
    created_at: datetime | None = None
