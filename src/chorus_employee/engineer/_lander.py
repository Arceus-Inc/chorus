"""The Engineer's outcome lander — "done" means a PR landed and integrated (spec 04 §2, spec 06 §2).

The Engineer's outcome is the full *PR → CI → merge*: CI-green is the Command DoD (enforced by the
beat, so it has already passed when ``land`` runs); this lander provides the *PR* and the *merge*. It
snapshots the engineer's branch-isolated worktree (commits the work on ``chorus/{employee}``), then
integrates that branch into the company ``main`` so the next employee branches off the shipped work,
and returns the canonical ``pr`` :class:`~chorus.outcomes.Artifact`.

A conflicting integration is **recorded, not raised** (``merged=False``) — the PR still stands for a
human/reviewer to resolve; the workspace is never left mid-merge. (A future §5 ``board_approval`` gate
would sit in front of the merge; until then a green beat integrates.)

The artifact reference is **host-safe** (spec 04 §2): branch + commit + a *relative* worktree pointer,
never a host-absolute path.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee._authorship import author_for, commit_message

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Ledger, Task


class EngineerLander:
    """Land a passed Engineer beat as a ``pr`` artifact (the branch + its committed work)."""

    outcome_kind = "pr"

    def __init__(self, company_root: Path, ledger: Ledger | None = None) -> None:
        self._company_root = company_root
        self._ledger = ledger

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the assignee's worktree, integrate it into ``main``, and return the ``pr`` artifact."""
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a PR")
        workspace = CompanyWorkspace(self._company_root)
        author = author_for(employee_id, self._ledger)
        message = commit_message(task)
        commit = workspace.snapshot(
            employee_id, author=author, message=message
        )  # commit the work on chorus/{employee} — the PR tip, authored by the employee
        merge = workspace.merge(
            employee_id, author=author, message=message
        )  # PR → integrate into the company main (conflict-safe)
        return Artifact(
            task_id=task.id,
            type=ArtifactType.PR,
            is_primary=True,
            resource_ref={
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "worktree": f"worktrees/{employee_id}",  # relative to the company root — no host path
                "merged": merge.merged,
                "into": merge.into,
            },
        )


def engineer_lander(company_root: Path, ledger: Ledger | None = None) -> EngineerLander:
    """The Engineer's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return EngineerLander(company_root, ledger)


__all__ = ["EngineerLander", "engineer_lander"]
