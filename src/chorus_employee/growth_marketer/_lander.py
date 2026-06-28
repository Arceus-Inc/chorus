"""The Growth Marketer's outcome lander — "done" means the real artifact landed (spec GM §2, §8).

Mira's outcome is one of three, picked by the beat's action class (the same :func:`classify_action`
the DoD uses, so the verifier and the landed artifact always agree):

- ``backtest`` → a ``backtest_report`` doc (the offline score-and-rank report);
- ``brief``    → a ``campaign_brief`` doc (the reviewed plan);
- ``launch``   → an ``experiment_launched`` artifact (the live experiment handle).

It snapshots the assignee's branch-isolated worktree, integrates it into the company ``main`` so the
next beat branches off the shipped work, and returns the canonical :class:`~chorus.outcomes.Artifact`
— branch + commit + a relative worktree pointer, never a host-absolute path (spec 04 §2). The
deliverable is recorded whether or not the file is present (``present``); the DoD is what gates an
absent artifact from ever reaching ``done``.

Dream-free: pure git (via :class:`~chorus.workspace.CompanyWorkspace`) + ledger-free metadata.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from chorus.outcomes import Artifact, ArtifactType
from chorus.workspace import CompanyWorkspace
from chorus_employee.growth_marketer._brief import (
    BACKTEST_REPORT_DOC,
    CAMPAIGN_BRIEF_DOC,
    EXPERIMENT_LAUNCH_DOC,
)
from chorus_employee.growth_marketer._dod import ActionClass, classify_action

if TYPE_CHECKING:
    from pathlib import Path

    from chorus.ledger import Task

# The outcome slug this role lands under (RolePlugin.outcome_kind). One slug, three artifact shapes
# resolved by action class at land time.
GROWTH_OUTCOME_KIND = "growth_outcome"

# action class → (artifact ``kind`` label, deliverable filename, artifact type)
_ARTIFACT_BY_ACTION: dict[ActionClass, tuple[str, str, ArtifactType]] = {
    ActionClass.BACKTEST: ("backtest_report", BACKTEST_REPORT_DOC, ArtifactType.DOC),
    ActionClass.BRIEF: ("campaign_brief", CAMPAIGN_BRIEF_DOC, ArtifactType.DOC),
    ActionClass.LAUNCH: ("experiment_launched", EXPERIMENT_LAUNCH_DOC, ArtifactType.ARTIFACT),
}


class GrowthMarketerLander:
    """Land a passed Growth Marketer beat as its action-class artifact (spec GM §2, §8)."""

    outcome_kind = GROWTH_OUTCOME_KIND

    def __init__(self, company_root: Path) -> None:
        self._company_root = company_root

    async def land(self, task: Task, result: Any) -> Artifact:
        """Snapshot the worktree, integrate into ``main``, and return the action-class artifact."""
        del result  # the deliverable is the worktree file, not the beat output
        employee_id = task.assignee_employee_id
        if employee_id is None:
            raise ValueError(f"task {task.id!r} has no assignee — cannot land a growth outcome")
        action = classify_action(task.intent)
        kind, filename, artifact_type = _ARTIFACT_BY_ACTION[action]
        workspace = CompanyWorkspace(self._company_root)
        doc = workspace.worktree_for(employee_id).path / filename
        present = doc.is_file() and doc.stat().st_size > 0
        commit = workspace.snapshot(employee_id)  # commit the deliverable on chorus/{employee}
        # Integrate into company ``main`` so the next beat branches off the shipped work
        # (conflict-safe — a conflicting merge is recorded, not raised).
        merge = workspace.merge(employee_id)
        return Artifact(
            task_id=task.id,
            type=artifact_type,
            is_primary=True,
            resource_ref={
                "kind": kind,
                "branch": f"chorus/{employee_id}",
                "commit": commit,
                "doc": filename,  # relative to the worktree — no host path
                "present": present,
                "merged": merge.merged,
                "into": merge.into,
            },
        )


def growth_marketer_lander(company_root: Path) -> GrowthMarketerLander:
    """The Growth Marketer's :class:`~chorus.outcomes.OutcomeLander`, rooted at the org workspace."""
    return GrowthMarketerLander(company_root)


__all__ = ["GROWTH_OUTCOME_KIND", "GrowthMarketerLander", "growth_marketer_lander"]
