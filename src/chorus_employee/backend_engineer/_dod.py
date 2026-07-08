"""The Backend Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

Like the Engineer, the Backend Engineer's DoD is a **reviewed build**: a read-only Reviewer discovers
the project's verify command and judges the diff; the kernel runs that command as the objective floor.
So ``done`` means the discovered build/test command exits 0 *and* the reviewer approved the diff — no
hardcoded, language-locked command (stack-agnostic by construction, spec §03). Artifact class ``pr`` —
it lands a PR, never an autonomous merge. The durable ``test_evidence`` floor (spec §10) is enforced
here: the rubric demands the reviewer fold a ``test_evidence/manifest.json`` verdict grep into the
discovered ``verify_command``, so "it was tested" is a file the kernel checks, not a claim the
reviewer takes on trust.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the diff implements the task to its contract, in its own file(s), built TEST-FIRST; the project "
    "builds and its tests pass; inputs are validated with no hardcoded secret; and any schema change "
    "stays backward-compatible. REJECT unless the durable proofs are present in the worktree: "
    '`test_evidence/manifest.json` shows `"verdict": "pass"` (every discovered gate — lint, '
    "types, unit — ran and passed); `test_plan.json` shows the tests were authored independently and "
    "seen failing FIRST (`red_evidence`); `review_verdict.json` shows an independent red-team "
    "`cleared` the diff (no high-severity risk — missing authz, N+1, injection, …); and — for a "
    "running service — `api_verdict.json` shows it booted and answered. Fold ALL FOUR checks into the "
    "`verify_command` you discover so the kernel runs them mechanically, e.g. append `&& grep -q "
    '\'\\"verdict\\": \\"pass\\"\' test_evidence/manifest.json && test -f test_plan.json && grep -q '
    "red_evidence test_plan.json && grep -q '\\\"cleared\\\": true' review_verdict.json` (and the "
    "api_verdict check for a service) to the project's real build/test command"
)


def backend_engineer_dod(intent: str) -> Verifier:
    """The Backend Engineer's DoD generator: a reviewed build — reviewer-judged + kernel-run tests."""
    return Verifier.reviewed_build(rubric=_RUBRIC, artifact_class="pr")


__all__ = ["backend_engineer_dod"]
