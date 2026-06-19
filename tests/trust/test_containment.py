"""Runtime containment for low-trust beats (§4) — the fail-closed conditions before a beat may run."""

from __future__ import annotations

import pytest

from chorus.roles import Isolation, PermissionMode, SandboxTier
from chorus.trust import ResolvedTrust, TrustBoundary, TrustDenied, TrustPreset
from chorus.trust._containment import assert_contained

pytestmark = pytest.mark.unit


def _low_trust(allow: set[str]) -> ResolvedTrust:
    return ResolvedTrust(
        sandbox=SandboxTier.READ_ONLY,
        permission_mode=PermissionMode.PLAN,
        net_allowed=False,
        preset=TrustPreset.LOW_TRUST_REVIEW,
        boundary=TrustBoundary(secret_ref_allowlist=frozenset(allow)),
    )


_STANDARD = ResolvedTrust(
    sandbox=SandboxTier.UNRESTRICTED,
    permission_mode=PermissionMode.DEFAULT,
    net_allowed=True,
    preset=TrustPreset.STANDARD,
    boundary=None,
)


def test_standard_beat_is_always_contained() -> None:
    # standard needs no containment — even a raw secret env is fine (it is trusted).
    assert_contained(_STANDARD, isolation=Isolation.WORKTREE, env=[("GITHUB_TOKEN", "ghp_raw")])


def test_low_trust_allows_an_allow_listed_ref() -> None:
    resolved = _low_trust({"ref:github_token"})
    assert_contained(
        resolved, isolation=Isolation.WORKTREE, env=[("GITHUB_TOKEN", "ref:github_token")]
    )


def test_low_trust_rejects_an_inline_secret() -> None:
    resolved = _low_trust({"ref:github_token"})
    with pytest.raises(TrustDenied, match="inline secret"):
        assert_contained(
            resolved, isolation=Isolation.WORKTREE, env=[("GITHUB_TOKEN", "ghp_rawvalue")]
        )


def test_low_trust_rejects_a_ref_outside_the_allow_list() -> None:
    resolved = _low_trust({"ref:github_token"})
    with pytest.raises(TrustDenied, match="allow-list"):
        assert_contained(
            resolved, isolation=Isolation.WORKTREE, env=[("AWS_SECRET", "ref:aws_secret")]
        )


def test_low_trust_requires_an_isolated_worktree() -> None:
    resolved = _low_trust(set())
    with pytest.raises(TrustDenied, match="worktree"):
        assert_contained(resolved, isolation=Isolation.REMOTE, env=[])


def test_low_trust_passes_non_secret_env_through() -> None:
    resolved = _low_trust(set())
    assert_contained(resolved, isolation=Isolation.WORKTREE, env=[("PATH", "/usr/bin"), ("HOME", "/h")])
