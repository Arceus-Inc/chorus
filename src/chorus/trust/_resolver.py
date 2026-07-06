"""Layered trust resolution (§4) — intersect employee ∩ task ∩ run, narrower wins, fail-closed.

The effective trust for a beat is the *most contained* of its three policy sources: the employee's role
posture (its sandbox tier + permission mode), the task's preset, and the run's preset. Every axis takes
the narrower value; a ``low_trust_review`` layer with no concrete boundary — or an unknown preset — is
**denied** (the beat must not run), per spec 04 §4.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chorus.roles import PermissionMode, SandboxTier
from chorus.trust._boundary import TrustBoundary
from chorus.trust._preset import TrustPreset, TrustProfile, profile_for, sandbox_rank

# Restrictiveness of a permission mode — lower is more contained (PLAN is read-only planning).
_MODE_RANK: dict[PermissionMode, int] = {
    PermissionMode.PLAN: 0,
    PermissionMode.DEFAULT: 1,
    PermissionMode.ACCEPT_EDITS: 2,
    PermissionMode.DONT_ASK: 3,
}


class TrustDenied(RuntimeError):
    """The resolved trust cannot be granted — the beat must not run (fail-closed, spec 04 §4)."""


@dataclass(frozen=True)
class ResolvedTrust:
    """The effective per-beat trust after intersecting all layers (spec 04 §4)."""

    sandbox: SandboxTier
    permission_mode: PermissionMode
    net_allowed: bool
    preset: TrustPreset
    boundary: TrustBoundary | None


def resolve_trust(
    *,
    role_sandbox: SandboxTier,
    role_permission_mode: PermissionMode = PermissionMode.DEFAULT,
    task_preset: TrustPreset,
    run_preset: TrustPreset = TrustPreset.STANDARD,
    boundary: TrustBoundary | None = None,
) -> ResolvedTrust:
    """Intersect the trust layers into one effective posture — the narrower wins on every axis."""
    task_profile = _profile(task_preset)
    run_profile = _profile(run_preset)

    sandbox = _narrowest_sandbox([role_sandbox, task_profile.max_sandbox, run_profile.max_sandbox])
    mode = _most_restrictive_mode(
        [role_permission_mode, task_profile.permission_mode, run_profile.permission_mode]
    )
    net = task_profile.net_allowed and run_profile.net_allowed
    preset = _narrower_preset(task_preset, run_preset)

    if profile_for(preset).requires_boundary and boundary is None:
        raise TrustDenied(f"{preset.value} requires a concrete boundary — none supplied")
    return ResolvedTrust(
        sandbox=sandbox, permission_mode=mode, net_allowed=net, preset=preset, boundary=boundary
    )


def _profile(preset: TrustPreset) -> TrustProfile:
    try:
        return profile_for(preset)
    except KeyError as exc:  # an unknown / unsupported preset fails closed
        raise TrustDenied(f"unsupported trust preset {preset!r}") from exc


def _narrowest_sandbox(tiers: Iterable[SandboxTier]) -> SandboxTier:
    return min(tiers, key=sandbox_rank)


def _most_restrictive_mode(modes: Iterable[PermissionMode]) -> PermissionMode:
    return min(modes, key=_MODE_RANK.__getitem__)


def _narrower_preset(task_preset: TrustPreset, run_preset: TrustPreset) -> TrustPreset:
    low = TrustPreset.LOW_TRUST_REVIEW
    return low if low in (task_preset, run_preset) else TrustPreset.STANDARD


__all__ = ["ResolvedTrust", "TrustDenied", "resolve_trust"]
