"""The Analyst's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

An Analyst's deliverable is a written findings doc; "done" is the findings being judged sound by a
Reviewer against the question (spec 06 §2: Analyst → AgentReview). The artifact class is ``finding``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "You are judging a FINISHED artifact: the file `findings.md` produced by an analyst. Use "
    "`read_file` to read `findings.md` (you have read_file). PASS it when `findings.md` is present, "
    "non-empty, and answers every part of the task's question with specific, numeric, evidence-backed "
    "conclusions that are internally consistent. You are read-only by design: you do NOT have, and do "
    "NOT need, warehouse_query / notebook_run / a shell / subagents, and you must NOT require re-running "
    "queries, re-executing code, STDOUT logs, regenerated charts, or any other process evidence — the "
    "committed `findings.md` IS the evidence. Never claim you cannot verify: read the file and assess "
    "its content. FAIL only if `findings.md` is missing, an answer is absent, vague, or self-contradictory."
)


def analyst_dod(intent: str) -> Verifier:
    """The Analyst's DoD generator (spec 04): a Reviewer judges the findings against the rubric."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="finding")


__all__ = ["analyst_dod"]
