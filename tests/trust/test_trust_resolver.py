"""Layered trust resolution (§4) — intersect employee ∩ task ∩ run, narrower wins, fail-closed."""

from __future__ import annotations

import pytest

from chorus.roles import PermissionMode, SandboxTier
from chorus.trust import TrustBoundary, TrustPreset
from chorus.trust._resolver import ResolvedTrust, TrustDenied, resolve_trust

pytestmark = pytest.mark.unit

_BOUNDARY = TrustBoundary(secret_ref_allowlist=frozenset({"ref:token"}))


def test_standard_keeps_the_role_posture() -> None:
    out = resolve_trust(
        role_sandbox=SandboxTier.UNRESTRICTED,
        role_permission_mode=PermissionMode.DEFAULT,
        task_preset=TrustPreset.STANDARD,
    )
    assert isinstance(out, ResolvedTrust)
    assert out.sandbox is SandboxTier.UNRESTRICTED
    assert out.permission_mode is PermissionMode.DEFAULT
    assert out.net_allowed is True
    assert out.preset is TrustPreset.STANDARD


def test_low_trust_task_clamps_an_unrestricted_role() -> None:
    out = resolve_trust(
        role_sandbox=SandboxTier.UNRESTRICTED,
        role_permission_mode=PermissionMode.DEFAULT,
        task_preset=TrustPreset.LOW_TRUST_REVIEW,
        boundary=_BOUNDARY,
    )
    assert out.sandbox is SandboxTier.READ_ONLY  # narrower wins
    assert out.permission_mode is PermissionMode.PLAN
    assert out.net_allowed is False
    assert out.preset is TrustPreset.LOW_TRUST_REVIEW


def test_narrower_role_is_not_widened_by_a_standard_task() -> None:
    out = resolve_trust(
        role_sandbox=SandboxTier.READ_ONLY,
        task_preset=TrustPreset.STANDARD,
    )
    assert out.sandbox is SandboxTier.READ_ONLY  # a standard task never widens the role


def test_run_layer_can_clamp_further() -> None:
    out = resolve_trust(
        role_sandbox=SandboxTier.UNRESTRICTED,
        task_preset=TrustPreset.STANDARD,
        run_preset=TrustPreset.LOW_TRUST_REVIEW,
        boundary=_BOUNDARY,
    )
    assert out.sandbox is SandboxTier.READ_ONLY  # the run layer alone tightens it


def test_low_trust_without_a_boundary_is_denied() -> None:
    with pytest.raises(TrustDenied):
        resolve_trust(
            role_sandbox=SandboxTier.REPO_WRITE,
            task_preset=TrustPreset.LOW_TRUST_REVIEW,
            boundary=None,  # no concrete scope → fail closed
        )


def test_standard_needs_no_boundary() -> None:
    out = resolve_trust(role_sandbox=SandboxTier.REPO_WRITE, task_preset=TrustPreset.STANDARD)
    assert out.boundary is None and out.preset is TrustPreset.STANDARD
