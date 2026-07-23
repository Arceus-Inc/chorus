"""The Marketer's outcome lander — "done" means a content draft landed in the worktree (design doc §09).

A Marketer's deliverable is a drafted content artifact in its worktree — content, creative-set,
sequence, or campaign. This lander snapshots the assignee's branch-isolated worktree (commits the
draft on ``chorus/{employee}``) and returns the canonical ``content`` :class:`~chorus.outcomes.Artifact`
pointing at the file — branch + commit + a relative worktree pointer, never a host-absolute path.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.marketer._brief import MARKETER_CONTENT_DOC

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task


class MarketerLander:
    """Land a passed Marketer beat as a ``content`` artifact (the committed draft)."""

    outcome_kind = "content"

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``content`` artifact for its draft."""
        del result  # the deliverable is the worktree's content file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land content")
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / MARKETER_CONTENT_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(employee_id)
        return Artifact(
            task_id=task.id,
            type=ArtifactType.ARTIFACT,
            is_primary=True,
            resource_ref={
                "kind": "content_draft",
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": MARKETER_CONTENT_DOC,
                "present": present,
            },
        )


def marketer_lander(company_root: Path) -> MarketerLander:
    """The Marketer's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return MarketerLander(company_root)


__all__ = ["MarketerLander", "marketer_lander"]
