"""The Designer's outcome lander — "done" means a design spec landed in the worktree (designer §09).

A Designer's deliverable is a committed design spec in its worktree — the layout, the tokens/components
used, the states, and the a11y notes. This lander snapshots the assignee's branch-isolated worktree
(commits the spec on ``chorus/{employee}``) and returns the canonical ``design``
:class:`~chorus.outcomes.Artifact` pointing at the file — branch + commit + a relative worktree pointer,
never a host-absolute path.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger metadata. A direct
re-point of the Marketer's lander onto the design substrate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.designer._brief import DESIGN_SPEC_DOC

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task


class DesignerLander:
    """Land a passed Designer beat as a ``design`` artifact (the committed design spec)."""

    outcome_kind = "design"

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree and return the ``design`` artifact for its spec."""
        del result  # the deliverable is the worktree's design spec, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land design")
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / DESIGN_SPEC_DOC
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(employee_id)
        return Artifact(
            task_id=task.id,
            type=ArtifactType.ARTIFACT,
            is_primary=True,
            resource_ref={
                "kind": "design_spec",
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": DESIGN_SPEC_DOC,
                "present": present,
            },
        )


def designer_lander(company_root: Path) -> DesignerLander:
    """The Designer's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return DesignerLander(company_root)


__all__ = ["DesignerLander", "designer_lander"]
