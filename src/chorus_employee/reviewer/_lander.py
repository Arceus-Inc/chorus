"""The Reviewer's outcome lander — records its verdict as a durable ``verdict`` artifact (spec 04 §2).

A Reviewer's deliverable is the judgment itself. The verdict was recorded into the work task's
``agent_review`` DoD by the ``submit_verdict`` tool during the beat; this lander reads it back from the
ledger and persists it as the canonical ``verdict`` artifact, so the decision + feedback are a durable,
reviewable record (not just a transient tool call).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Task


class ReviewerLander:
    """Land a passed Reviewer beat as a ``verdict`` artifact (the recorded approve/block decision)."""

    outcome_kind = "verdict"

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    async def land(self, task: Task, result: Any) -> Artifact:
        """Record the reviewer's verdict — read from the work task's DoD, never from the beat output."""
        del result  # the deliverable is the recorded DoD verdict, read from the ledger
        dod = self._ledger.dod.get_for_task(task.id)
        verdict = dod.verdict if dod is not None and dod.verdict is not None else {}
        return Artifact(
            task_id=task.id,
            type=ArtifactType.VERDICT,
            is_primary=True,
            resource_ref={"kind": "verdict", **verdict},
        )


def reviewer_lander(ledger: Ledger) -> ReviewerLander:
    """The Reviewer's outcome lander, bound to the ledger it reads its verdict from."""
    return ReviewerLander(ledger)


__all__ = ["ReviewerLander", "reviewer_lander"]
