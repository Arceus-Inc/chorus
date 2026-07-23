"""The Manager's outcome lander — "done" means the delegated subtree landed (spec 04 §2, M3 §5).

A Manager's deliverable is not code: it is the **completed subtree** it delegated and integrated. When
the integrate beat passes (the kernel's Mechanical DoD: every child terminal), this lander records a
``subtree`` artifact capturing each child and its terminal status — the durable, reviewable trace of
what the manager shipped.

Dream-free: it reads the children from the ledger it closed over (the manager owns no worktree of its
own). The artifact reference is host-safe (ids + statuses, never a path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType

if TYPE_CHECKING:
    from chorus.ledger import Ledger, Task


class ManagerLander:
    """Land a passed Manager integrate beat as a ``subtree`` artifact (its children + their outcomes)."""

    outcome_kind = "subtree"

    def __init__(self, ledger: Ledger) -> None:
        self._ledger = ledger

    async def land(self, task: Task, result: Any) -> Artifact:
        """Record the completed subtree: every child id, its assignee, and its terminal status."""
        del (
            result
        )  # the deliverable is the subtree state, read from the ledger — not the beat output
        children = self._ledger.tasks.children(task.id)
        return Artifact(
            task_id=task.id,
            type=ArtifactType.ARTIFACT,
            is_primary=True,
            resource_ref={
                "kind": "subtree",
                "children": [
                    {"id": c.id, "assignee": c.assignee_employee_id, "status": c.status.value}
                    for c in children
                ],
            },
        )


def manager_lander(ledger: Ledger) -> ManagerLander:
    """The Manager's :class:`~chorus.outcomes.OutcomeLander`, reading its subtree from the ledger."""
    return ManagerLander(ledger)


__all__ = ["ManagerLander", "manager_lander"]
