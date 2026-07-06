"""Per-beat trust narrowing at materialize (§4 trust presets, spec 04 §4).

The factory materializes a fresh harness for every beat; this is where the task's effective trust is
applied. ``apply_trust`` resolves the layered preset over the role config, asserts containment, and
returns a config **clamped** to the resolved ceiling (a low-trust beat → read-only sandbox + plan-mode).
A :class:`~chorus.trust.TrustDenied` propagates — the kernel must not materialize an uncontained beat.
"""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from chorus.roles import Isolation, PermissionMode, RoleBeatConfig, SandboxTier
from chorus.trust import (
    TrustBoundary,
    TrustPolicy,
    TrustPreset,
    assert_contained,
    resolve_trust,
)

if TYPE_CHECKING:
    from chorus.ledger import Task

_ALLOWLIST_KEY = "secret_ref_allowlist"


def apply_trust(
    config: RoleBeatConfig, *, task: Task | None, policy: TrustPolicy
) -> RoleBeatConfig:
    """Narrow ``config`` to the task's effective trust — or raise ``TrustDenied`` (spec 04 §4)."""
    if task is None:
        return config  # no task context → the role's standing posture stands
    explicit = TrustPreset(task.trust_preset) if task.trust_preset is not None else None
    preset = policy.preset_for(origin=task.origin_kind, explicit=explicit)
    boundary = _boundary_from(task.trust_boundary)

    resolved = resolve_trust(
        role_sandbox=SandboxTier(config.sandbox),
        role_permission_mode=PermissionMode(config.permission_mode),
        task_preset=preset,
        boundary=boundary,
    )
    assert_contained(resolved, isolation=Isolation(config.isolation), env=config.env)
    return replace(
        config,
        sandbox=resolved.sandbox.value,
        permission_mode=resolved.permission_mode.value,
    )


def _boundary_from(raw: dict[str, object] | None) -> TrustBoundary | None:
    if raw is None:
        return None
    allow = raw.get(_ALLOWLIST_KEY, [])
    refs = frozenset(str(ref) for ref in allow) if isinstance(allow, list) else frozenset()
    return TrustBoundary(secret_ref_allowlist=refs)


__all__ = ["apply_trust"]
