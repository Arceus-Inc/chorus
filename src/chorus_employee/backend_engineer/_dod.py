"""The Backend Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

Like the Engineer, the Backend Engineer's DoD is a **reviewed build**: a read-only Reviewer discovers
the project's verify command and judges the diff; the kernel runs that command as the objective floor.
So ``done`` means the discovered build/test command exits 0 *and* the reviewer approved the diff — no
hardcoded, language-locked command (stack-agnostic by construction, spec §03). Artifact class ``pr`` —
it lands a PR, never an autonomous merge. The durable ``test_evidence`` floor is a later slice.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the diff implements the task to its contract, in its own file(s), with a test for new behaviour; "
    "the project builds and its tests pass; inputs are validated with no hardcoded secret; and any "
    "schema change stays backward-compatible"
)


def backend_engineer_dod(intent: str) -> Verifier:
    """The Backend Engineer's DoD generator: a reviewed build — reviewer-judged + kernel-run tests."""
    return Verifier.reviewed_build(rubric=_RUBRIC, artifact_class="pr")


__all__ = ["backend_engineer_dod"]
