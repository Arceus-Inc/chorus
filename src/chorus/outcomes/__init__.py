"""Outcomes, DoD & governance (spec 04).

The chorus differentiator: because it is dream-native, the evaluator verifies
the *real artifact* against a typed Definition-of-Done. This package holds the
typed :class:`Verifier` (DoD) tiers and the :class:`OutcomeLander` seam.
"""

from __future__ import annotations

from chorus.outcomes._deliverable import (
    DeliverableKind,
    classify_deliverable,
    native_kind_for_role,
    resolve_delivery_verifier,
)
from chorus.outcomes._lander import Artifact, ArtifactType, OutcomeLander
from chorus.outcomes._outcome_kind import OutcomeKind
from chorus.outcomes._platform import (
    Check,
    PlatformInfo,
    detect_platform,
    file_exists,
    file_matches,
    file_matches_any,
    glob_at_least,
    min_words,
    python_check,
    runtime_brief_block,
)
from chorus.outcomes._pr_landing import PrIntegration, PrLanding, pr_landing, pr_landing_of
from chorus.outcomes._registry import LanderRegistry
from chorus.outcomes._revision import Obligation, RevisionDirection, classify
from chorus.outcomes._verifier import (
    AgentReview,
    Command,
    DoDKind,
    DoDSpec,
    HumanApproval,
    VerificationStep,
    Verifier,
)

__all__ = [
    "AgentReview",
    "Artifact",
    "ArtifactType",
    "Check",
    "Command",
    "DeliverableKind",
    "DoDKind",
    "DoDSpec",
    "HumanApproval",
    "LanderRegistry",
    "Obligation",
    "OutcomeKind",
    "OutcomeLander",
    "PlatformInfo",
    "PrIntegration",
    "PrLanding",
    "RevisionDirection",
    "VerificationStep",
    "Verifier",
    "classify",
    "classify_deliverable",
    "detect_platform",
    "file_exists",
    "file_matches",
    "file_matches_any",
    "glob_at_least",
    "min_words",
    "native_kind_for_role",
    "pr_landing",
    "pr_landing_of",
    "python_check",
    "resolve_delivery_verifier",
    "runtime_brief_block",
]
