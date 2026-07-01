"""The Marketer's Definition of Done — intent -> typed :class:`~chorus.outcomes.Verifier`.

The Marketer's DoD is **action-class** (design doc S09): governed against spending or sending
recklessly, not against being wrong. The verifier tiers:

- A reversible draft (content, creative-set) -> Command (well-formed check) or AgentReview.
- Anything going live -> AgentReview (the Brand-Critic) + HumanApproval.

For Slice 0, all marketer output is draft content verified by an AgentReview (a Reviewer
judges on-brand fidelity). The artifact class is ``content``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the content is on-brand, on-voice, and answers the brief; every claim is substantiated "
    "or explicitly flagged as needing proof; the piece is structured for the target channel "
    "and ready to stage for go-live approval"
)


def marketer_dod(intent: str) -> Verifier:
    """The Marketer's DoD generator: a Reviewer judges the draft against brand-fidelity."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="content")


__all__ = ["marketer_dod"]
