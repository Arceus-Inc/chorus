"""The Analyst's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

An Analyst's deliverable is a written findings doc; "done" is the findings being judged sound by a
Reviewer against the question (spec 06 §2: Analyst → AgentReview). The artifact class is ``finding``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "Judge ONLY the findings file (findings.md) as a finished artifact. PASS it when it is present, "
    "non-empty, and answers every part of the task's question with specific, numeric, evidence-backed "
    "conclusions consistent with the data. Do NOT require re-running code, re-spawning subagents, "
    "command/STDOUT logs, or any other process evidence — you are read-only and the committed artifact "
    "IS the evidence. Fail only if an answer is missing, vague, or contradicts the data."
)


def analyst_dod(intent: str) -> Verifier:
    """The Analyst's DoD generator (spec 04): a Reviewer judges the findings against the rubric."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="finding")


__all__ = ["analyst_dod"]
