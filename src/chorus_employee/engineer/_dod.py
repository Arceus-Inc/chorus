"""The Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

The Engineer's DoD is a **reviewed build** (M3 reviewed-build): a read-only Reviewer discovers the
project's verify command and judges the diff; the kernel runs that command as the objective floor. So
``done`` means the discovered build/test command exits 0 *and* the reviewer approved the diff — with no
hardcoded, language-locked command. The verifier's artifact class is ``pr`` — the Engineer lands a PR.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the diff implements the task correctly and cleanly, in its own file(s), with a test for new "
    "behaviour; the project builds and its tests pass"
)


def engineer_dod(intent: str) -> Verifier:
    """The Engineer's DoD generator (spec 04): a reviewed build — reviewer-judged + kernel-run tests."""
    return Verifier.reviewed_build(rubric=_RUBRIC, artifact_class="pr")


__all__ = ["engineer_dod"]
