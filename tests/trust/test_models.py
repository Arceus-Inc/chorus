"""Trust preset models (§4) — the preset → profile mapping, policy derivation, sandbox ordering."""

from __future__ import annotations

import pytest

from chorus.ledger import OriginKind
from chorus.roles import PermissionMode, SandboxTier
from chorus.trust import (
    TrustBoundary,
    TrustPolicy,
    TrustPreset,
    profile_for,
    sandbox_rank,
)

pytestmark = pytest.mark.unit


def test_standard_profile_does_not_clamp() -> None:
    profile = profile_for(TrustPreset.STANDARD)
    assert profile.max_sandbox is SandboxTier.UNRESTRICTED
    assert profile.permission_mode is PermissionMode.DEFAULT
    assert profile.net_allowed is True
    assert profile.requires_boundary is False


def test_low_trust_profile_clamps_to_read_only_plan_no_net() -> None:
    profile = profile_for(TrustPreset.LOW_TRUST_REVIEW)
    assert profile.max_sandbox is SandboxTier.READ_ONLY
    assert profile.permission_mode is PermissionMode.PLAN
    assert profile.net_allowed is False
    assert profile.requires_boundary is True


def test_sandbox_rank_orders_by_capability() -> None:
    assert sandbox_rank(SandboxTier.READ_ONLY) < sandbox_rank(SandboxTier.REPO_WRITE)
    assert sandbox_rank(SandboxTier.REPO_WRITE) < sandbox_rank(SandboxTier.REPO_WRITE_NET)
    assert sandbox_rank(SandboxTier.REPO_WRITE_NET) < sandbox_rank(SandboxTier.UNRESTRICTED)


def test_policy_explicit_preset_overrides_origin() -> None:
    policy = TrustPolicy(low_trust_origins=frozenset({OriginKind.MANUAL}))
    # explicit wins even when the origin would derive otherwise.
    assert policy.preset_for(origin=OriginKind.MANUAL, explicit=TrustPreset.STANDARD) is TrustPreset.STANDARD
    assert (
        policy.preset_for(origin=OriginKind.DECOMPOSITION, explicit=TrustPreset.LOW_TRUST_REVIEW)
        is TrustPreset.LOW_TRUST_REVIEW
    )


def test_policy_derives_low_trust_from_a_flagged_origin() -> None:
    policy = TrustPolicy(low_trust_origins=frozenset({OriginKind.STRANDED_RECOVERY}))
    assert policy.preset_for(origin=OriginKind.STRANDED_RECOVERY, explicit=None) is TrustPreset.LOW_TRUST_REVIEW
    assert policy.preset_for(origin=OriginKind.MANUAL, explicit=None) is TrustPreset.STANDARD


def test_empty_policy_is_standard_everywhere() -> None:
    policy = TrustPolicy()
    assert policy.preset_for(origin=OriginKind.MANUAL, explicit=None) is TrustPreset.STANDARD


def test_boundary_holds_a_secret_ref_allowlist() -> None:
    boundary = TrustBoundary(secret_ref_allowlist=frozenset({"ref:github_token"}))
    assert "ref:github_token" in boundary.secret_ref_allowlist
