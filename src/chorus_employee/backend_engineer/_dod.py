"""The Backend Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

Operator decision (2026-07-18): employees verify their own work — no system verifier and no kernel
evidence machinery. The Backend Engineer's DoD is a **self-judged agent review**: dream's single
in-beat evaluator judges the rubric during the beat itself, and that evaluation IS the verdict — no
second Reviewer beat, no evidence-bundle files the kernel parses. The rubric keeps the substance the
employee can check in-beat: tests exist and pass when run, the diff implements the contract, inputs
are validated, no secrets. Artifact class ``pr`` — it lands a PR, never an autonomous merge.
"""

from __future__ import annotations

import re

from chorus.outcomes import Verifier

# The standing routines declare their contract in the intent itself ("Report only" / "Report and
# propose only" — authored in ._routines, same package): a report's DoD is a judged report, not a
# TDD PR. Found live 2026-07-18 in two companies: report-only beats under the reviewed build's
# strict-TDD gate failed 0.0 — the evaluator could not even read the repo.
_REPORT_ONLY_RE = re.compile(r"\breport(?:\s+and\s+propose)?\s+only\b", re.IGNORECASE)

_REPORT_RUBRIC = (
    "the deliverable is a REPORT, not production code: a markdown or JSON artifact in the worktree "
    "states what was scanned/checked, each finding with concrete evidence (file paths, tool "
    "output, or an explicit 'nothing found' / 'not declared in this repo' — absence honestly "
    "reported is a PASSING finding), and bounded proposed next steps. Judge substance: PASS a "
    "report that scanned what exists and reported truthfully, even when the repo is young and the "
    "answer is 'nothing to scan yet'. FAIL only for a concrete defect: no report artifact, "
    "invented numbers/sources, or production code changes smuggled into a report-only task."
)

_RUBRIC = (
    "the diff implements the task to its contract, in its own file(s), built TEST-FIRST: real tests "
    "for the new behaviour exist in the worktree and PASS when actually run, and the project's own "
    "build/test command exits 0. Inputs are validated at the boundaries with no hardcoded secret, "
    "and any schema change stays backward-compatible. REJECT generated runtime state in the diff — "
    "database files, caches, logs, coverage output, and build output — unless the task explicitly "
    "requires a versioned fixture. Judge by running the checks yourself in the worktree, not by "
    "trusting claims: a test suite that was never run, or a diff that skips the contract, is not done."
)


def backend_engineer_dod(intent: str) -> Verifier:
    """The Backend Engineer's DoD generator: a self-judged agent review — or a judged report for
    report-only work (the standing routines' contract)."""
    if _REPORT_ONLY_RE.search(intent):
        return Verifier.agent_review(rubric=_REPORT_RUBRIC, artifact_class="finding")
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="pr")


__all__ = ["backend_engineer_dod"]
