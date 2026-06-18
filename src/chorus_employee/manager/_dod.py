"""The Manager's Definition of Done — intent → typed :class:`~chorus.outcomes.Verifier`.

A Manager's deliverable is a **completed subtree**: "done" means every child is terminal and the work
is integrated, verified by a Reviewer (``AgentReview``). The verifier's artifact class is ``subtree``.
"""

from __future__ import annotations

from chorus.outcomes import Verifier


def manager_dod(intent: str) -> Verifier:
    """The Manager's DoD generator (spec 04): children terminal + integrated, reviewer-verified."""
    return Verifier.agent_review(
        rubric="all children terminal and integrated", artifact_class="subtree"
    )


__all__ = ["manager_dod"]
