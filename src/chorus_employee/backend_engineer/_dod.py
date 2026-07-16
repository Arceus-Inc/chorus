"""The Backend Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

Like the Engineer, the Backend Engineer's DoD is a **reviewed build**: a read-only Reviewer discovers
the project's verify command and judges the diff; the kernel runs that command as the objective floor.
So ``done`` means the discovered build/test command exits 0 *and* the reviewer approved the diff — no
hardcoded, language-locked command (stack-agnostic by construction, spec §03). Artifact class ``pr`` —
it lands a PR, never an autonomous merge. The durable ``test_evidence`` floor (spec §10) is enforced
by the reviewed build's typed ``tdd_review_v1`` profile: the kernel parses the JSON evidence directly,
portably, and separately from the repository's build/test command.
"""

from __future__ import annotations

from chorus.outcomes import ReviewedBuildEvidenceProfile, Verifier

_RUBRIC = (
    "the diff implements the task to its contract, in its own file(s), built TEST-FIRST; the project "
    "builds and its tests pass; inputs are validated with no hardcoded secret; and any schema change "
    "stays backward-compatible. REJECT generated runtime state in the diff — database files, caches, "
    "logs, coverage output, and build output — unless the task explicitly requires a versioned fixture. "
    "REJECT unless the durable proofs are present in the worktree: "
    '`test_evidence/manifest.json` shows `"verdict": "pass"` (every discovered gate — lint, '
    'types, unit — ran and passed); `test_evidence/red.json` shows `"verdict": '
    '`"red-confirmed"` (the machine refused production changes before RED); `test_plan.json` shows '
    "the tests were authored independently; `review_verdict.json` shows an independent red-team "
    "`cleared` the diff (no high-severity risk — missing authz, N+1, injection, …); and — for a "
    "running service — `api_verdict.json` shows it booted and answered. The kernel validates the four "
    "structured TDD/review artifacts independently from the project's real build/test command; never "
    "compose evidence-file checks into that command."
)


def backend_engineer_dod(intent: str) -> Verifier:
    """The Backend Engineer's DoD generator: a reviewed build — reviewer-judged + kernel-run tests."""
    return Verifier.reviewed_build(
        rubric=_RUBRIC,
        artifact_class="pr",
        evidence_profile=ReviewedBuildEvidenceProfile.TDD_REVIEW_V1,
    )


__all__ = ["backend_engineer_dod"]
