"""The Engineer's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

Operator decision (2026-07-18): employees verify their own work — no system verifier. The Engineer's
DoD is a **self-judged agent review**: dream's single in-beat evaluator judges the rubric during the
beat, and that evaluation IS the verdict — no second Reviewer beat. The artifact class is ``pr`` —
the Engineer lands a PR.
"""

from __future__ import annotations

from chorus.outcomes import Verifier

_RUBRIC = (
    "the diff implements the task correctly and cleanly, in its own file(s), with a test for new "
    "behaviour; the project builds and its tests pass when actually run"
)


def engineer_dod(intent: str) -> Verifier:
    """The Engineer's DoD generator: a self-judged agent review rendered in-beat."""
    return Verifier.agent_review(rubric=_RUBRIC, artifact_class="pr")


__all__ = ["engineer_dod"]
