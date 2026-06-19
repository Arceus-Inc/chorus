"""§4 trust presets — ``standard`` / ``low_trust_review``, fail-closed (spec 04 §4).

A beat's effective trust is the intersection of the employee, task, and run layers (narrower wins);
``low_trust_review`` boxes a beat in for hostile / prompt-injected input (read-only, plan-mode, no-net,
secrets scrubbed to approved refs), and anything ambiguous is denied. The resolved trust is applied at
chorus's existing per-beat materialize boundary — no dream change.
"""

from __future__ import annotations

from chorus.trust._boundary import TrustBoundary, TrustPolicy
from chorus.trust._containment import assert_contained
from chorus.trust._preset import (
    TrustPreset,
    TrustProfile,
    profile_for,
    sandbox_rank,
)
from chorus.trust._resolver import ResolvedTrust, TrustDenied, resolve_trust

__all__ = [
    "ResolvedTrust",
    "TrustBoundary",
    "TrustDenied",
    "TrustPolicy",
    "TrustPreset",
    "TrustProfile",
    "assert_contained",
    "profile_for",
    "resolve_trust",
    "sandbox_rank",
]
