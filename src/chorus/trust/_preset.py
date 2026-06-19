"""Trust presets + profiles (§4) — what each preset clamps a beat to (spec 04 §4).

``standard`` is the role's normal posture (no clamp). ``low_trust_review`` is containment for hostile /
prompt-injected input: read-only sandbox, plan-mode, no network, and a required boundary. A preset is a
**ceiling**, never a widening — resolution only ever narrows.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from chorus.roles import PermissionMode, SandboxTier


class TrustPreset(StrEnum):
    """A named trust posture (spec 04 §4)."""

    STANDARD = "standard"
    LOW_TRUST_REVIEW = "low_trust_review"


@dataclass(frozen=True)
class TrustProfile:
    """The ceiling a preset imposes — the most a beat under it may do (spec 04 §4)."""

    max_sandbox: SandboxTier
    permission_mode: PermissionMode
    net_allowed: bool
    requires_boundary: bool


_PROFILES: dict[TrustPreset, TrustProfile] = {
    TrustPreset.STANDARD: TrustProfile(
        max_sandbox=SandboxTier.UNRESTRICTED,
        permission_mode=PermissionMode.DEFAULT,
        net_allowed=True,
        requires_boundary=False,
    ),
    TrustPreset.LOW_TRUST_REVIEW: TrustProfile(
        max_sandbox=SandboxTier.READ_ONLY,
        permission_mode=PermissionMode.PLAN,
        net_allowed=False,
        requires_boundary=True,
    ),
}

# Capability order — "narrower wins" is the lowest rank. Read-only is the most contained.
_SANDBOX_ORDER: tuple[SandboxTier, ...] = (
    SandboxTier.READ_ONLY,
    SandboxTier.REPO_WRITE,
    SandboxTier.REPO_WRITE_NET,
    SandboxTier.UNRESTRICTED,
)
_SANDBOX_RANK: dict[SandboxTier, int] = {tier: rank for rank, tier in enumerate(_SANDBOX_ORDER)}


def profile_for(preset: TrustPreset) -> TrustProfile:
    """The :class:`TrustProfile` a preset imposes."""
    return _PROFILES[preset]


def sandbox_rank(tier: SandboxTier) -> int:
    """The capability rank of a sandbox tier (lower = more contained)."""
    return _SANDBOX_RANK[tier]


__all__ = ["TrustPreset", "TrustProfile", "profile_for", "sandbox_rank"]
