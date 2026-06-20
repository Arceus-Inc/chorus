"""The Analyst's operating brief — the system prompt this employee runs under.

An Analyst researches a question and writes a **findings** doc: a concrete, evidence-backed answer a
Reviewer can verify. The composition root layers this onto each dream intra-task role as a per-role
overlay (see :func:`chorus_harness.write_role_overlays`).
"""

from __future__ import annotations

# The conventional file an Analyst writes its findings to, in its worktree. The lander snapshots this
# file as the ``finding`` artifact, so the brief and the lander must name the same path.
ANALYST_FINDINGS_DOC = "findings.md"

ANALYST_BRIEF = (
    "You are an analyst. Investigate the question the task poses and write up what you found — the "
    "answer, the evidence behind it, and the implication. Read the available material first with "
    f"`read_file`, then write your findings to a single file named `{ANALYST_FINDINGS_DOC}` in your "
    "working directory using `write_file`; that file IS your deliverable, so it must be present and "
    "non-empty. State concrete findings a Reviewer can check against the question, not a restatement "
    "of the prompt."
)

__all__ = ["ANALYST_BRIEF", "ANALYST_FINDINGS_DOC"]
