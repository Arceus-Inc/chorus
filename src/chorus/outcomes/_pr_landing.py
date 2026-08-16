"""Typed reading of whether a landed PR actually integrated into company main (BUG-005).

The lander records merge success on the PR artifact. ``done`` must not follow from a recorded
unmerged PR — this helper is the only place that interprets that storage so the scheduler never
treats a raw resource-ref map as a domain model.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from chorus.outcomes._lander import Artifact, ArtifactType


class PrIntegration(StrEnum):
    """Whether a landed PR artifact reports integration into company main."""

    MERGED = "merged"
    UNMERGED = "unmerged"
    NOT_RECORDED = "not_recorded"


@dataclass(frozen=True)
class PrLanding:
    """The typed landing disposition of one artifact for the done⇒landed gate."""

    integration: PrIntegration

    @property
    def blocks_done(self) -> bool:
        """True only when the artifact is a PR that explicitly failed to merge."""
        return self.integration is PrIntegration.UNMERGED


def pr_landing(artifact: Artifact) -> PrLanding:
    """Interpret an outcomes ``Artifact`` as a PR integration record."""
    return pr_landing_of(artifact.type.value, artifact.resource_ref)


def pr_landing_of(type_value: str, resource_ref: Mapping[str, object] | None) -> PrLanding:
    """Interpret a persisted artifact row as a PR integration record.

    Non-PR artifacts, and PRs that do not record a merge flag, do not block ``done`` — landing stays
    additive for those kinds. Only an explicit unmerged PR refuses finalisation.
    """
    if type_value != ArtifactType.PR.value:
        return PrLanding(integration=PrIntegration.NOT_RECORDED)
    merged = _recorded_merged(resource_ref)
    if merged is False:
        return PrLanding(integration=PrIntegration.UNMERGED)
    if merged is True:
        return PrLanding(integration=PrIntegration.MERGED)
    return PrLanding(integration=PrIntegration.NOT_RECORDED)


def _recorded_merged(resource_ref: Mapping[str, object] | None) -> bool | None:
    """The lander's ``merged`` flag when it is a real boolean; otherwise unknown."""
    if resource_ref is None:
        return None
    raw = resource_ref.get("merged")
    return raw if isinstance(raw, bool) else None


__all__ = ["PrIntegration", "PrLanding", "pr_landing", "pr_landing_of"]
