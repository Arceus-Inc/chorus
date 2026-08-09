"""The Reflection Coach's proposal-review Definition of Done."""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the reflection clusters concrete evidence from other agents, proposes only minimal reviewable "
    "diffs, includes representative-success replay checks, and does not apply any change"
)


def reflection_coach_dod(intent: str) -> Verifier:
    """Every coach beat is judged as a proposal, never as an applied change."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="reflection_proposal")


__all__ = ["reflection_coach_dod"]
