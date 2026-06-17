"""Outcomes, DoD & governance (spec 04).

The chorus differentiator: because it is dream-native, the evaluator verifies
the *real artifact* against a typed Definition-of-Done. This package holds the
typed :class:`Verifier` (DoD) tiers and the :class:`OutcomeLander` seam.
"""

from __future__ import annotations

from chorus.outcomes._lander import Artifact, ArtifactType, OutcomeLander
from chorus.outcomes._registry import LanderRegistry
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
    "Command",
    "DoDKind",
    "DoDSpec",
    "HumanApproval",
    "LanderRegistry",
    "OutcomeLander",
    "VerificationStep",
    "Verifier",
]
