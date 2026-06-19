"""Outcome landing — the role-specific "land the work" step (spec 04 §2).

"Done" is not "the run finished" — it is "the deliverable **landed** somewhere a
reviewer can verify it." Each role has an :class:`OutcomeLander`: an Engineer's
lands a PR (open → CI green → repair → merge); a PM's persists a spec artifact;
an Analyst's persists a finding. The kernel calls ``land`` after the beat and
records the resulting :class:`Artifact` on the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from chorus.ledger import Task


class ArtifactType(StrEnum):
    """The artifact classes the ledger records (spec 01 Cluster F)."""

    PR = "pr"
    DOC = "doc"
    FINDING = "finding"
    ARTIFACT = "artifact"
    WORKSPACE_FILE = "workspace_file"
    VERDICT = "verdict"


@dataclass(frozen=True)
class Artifact:
    """A landed deliverable — server-canonicalised metadata, not worker-supplied (spec 04 §2)."""

    task_id: str
    type: ArtifactType
    url: str | None = None
    external_id: str | None = None
    is_primary: bool = True
    resource_ref: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class OutcomeLander(Protocol):
    """Role-specific landing of a passed beat into a durable, reviewable artifact.

    Default impls live per role; a consumer can swap one in via the contract
    (spec 09 §4) without touching the kernel.
    """

    outcome_kind: str

    async def land(self, task: Task, result: Any) -> Artifact:
        """Persist the deliverable and return the canonical :class:`Artifact`.

        Strict completion pattern (spec 04 §2): generate + verify locally →
        persist artifact → link it in the final task comment → set status. A
        local path is never the sole access path.
        """
        ...


__all__ = [
    "Artifact",
    "ArtifactType",
    "OutcomeLander",
]
