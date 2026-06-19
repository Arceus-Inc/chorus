"""The trust boundary + policy (§4) — the concrete scope a low-trust beat is confined to.

A ``low_trust_review`` beat must carry a :class:`TrustBoundary` (its allow-list of secret refs); without
one it is denied (spec 04 §4). The :class:`TrustPolicy` derives a preset from a task's origin — the
auto-path, with an explicit ``task.trust_preset`` always winning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chorus.ledger import OriginKind
from chorus.trust._preset import TrustPreset


@dataclass(frozen=True)
class TrustBoundary:
    """The resources a low-trust beat may touch — its secret-ref allow-list (spec 04 §4).

    Refs only: a low-trust beat references secrets by handle (``ref:…``); a raw value is never inside
    the boundary (enforced by the no-inline-secrets containment check)."""

    secret_ref_allowlist: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class TrustPolicy:
    """Derive a task's trust preset from its origin — fail-closed default is ``standard`` (spec 04 §4)."""

    low_trust_origins: frozenset[OriginKind] = field(default_factory=frozenset)

    def preset_for(self, *, origin: OriginKind, explicit: TrustPreset | None) -> TrustPreset:
        """The preset for a task: an explicit setting always wins; else derive from the origin."""
        if explicit is not None:
            return explicit
        return (
            TrustPreset.LOW_TRUST_REVIEW
            if origin in self.low_trust_origins
            else TrustPreset.STANDARD
        )


__all__ = ["TrustBoundary", "TrustPolicy"]
