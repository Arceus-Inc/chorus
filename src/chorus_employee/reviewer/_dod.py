"""The Reviewer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

A Reviewer's deliverable is the verdict itself; "done" is the verdict being recorded (a human-approval
gate today). The verifier's artifact class is ``verdict``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier


def reviewer_dod(intent: str) -> Verifier:
    """The Reviewer's DoD generator (spec 04): the verdict is approved/recorded."""
    return Verifier.human_approval(artifact_class="verdict")


__all__ = ["reviewer_dod"]
