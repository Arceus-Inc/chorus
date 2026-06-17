"""The Engineer's outcome lander — "done" means a PR landed (spec 04 §2, spec 06 §2).

The Engineer's outcome is *PR opened, CI green*. CI-green is the Command DoD (enforced by the beat);
this lander provides the *PR*: it snapshots the engineer's branch-isolated worktree (commits the work
on ``chorus/{employee}``) and returns the canonical ``pr`` :class:`~chorus.outcomes.Artifact` pointing
at the branch + commit. The kernel records it on the ledger after the beat passes.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task


class EngineerLander:
    """Land a passed Engineer beat as a ``pr`` artifact (the branch + its committed work)."""

    outcome_kind = "pr"

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``pr`` artifact (branch + commit)."""
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a PR")
        workspace = CompanyWorkspace(self._company_root)
        commit = workspace.snapshot(employee_id)  # commit the work on chorus/{employee}
        worktree = workspace.worktree_for(employee_id).path
        return Artifact(
            task_id=task.id,
            type=ArtifactType.PR,
            is_primary=True,
            resource_ref={
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "worktree": str(worktree),
            },
        )


def engineer_lander(company_root: Path) -> EngineerLander:
    """The Engineer's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return EngineerLander(company_root)


__all__ = ["EngineerLander", "engineer_lander"]
