"""The Analyst's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

An Analyst's deliverable is a written findings doc; "done" is the findings being judged sound by a
Reviewer against the question (spec 06 §2: Analyst → AgentReview). The artifact class is ``finding``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the findings answer the task's question with concrete, evidence-backed conclusions; they are "
    "present, non-empty, and specific rather than a restatement of the prompt"
)


def analyst_dod(intent: str) -> Verifier:
    """The Analyst's DoD generator (spec 04): a Reviewer judges the findings against the rubric."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="finding")


__all__ = ["analyst_dod"]
