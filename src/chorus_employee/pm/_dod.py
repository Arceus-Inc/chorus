"""The PM's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

A PM's deliverable is a written plan/spec; "done" is the plan being judged sound by a Reviewer against
the task's intent (spec 06 §2: Product/PM → AgentReview). The verifier's artifact class is ``spec``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the plan addresses the task's goal with a concrete scope, decisions, and next steps; it is "
    "present, non-empty, and specific enough for an engineer to act on"
)


def pm_dod(intent: str) -> Verifier:
    """The PM's DoD generator (spec 04): a Reviewer judges the plan against the rubric."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="spec")


__all__ = ["pm_dod"]
