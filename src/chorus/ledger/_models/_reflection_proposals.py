"""Immutable, reviewable Reflection Coach proposals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReflectionTargetKind(StrEnum):
    """The managed surfaces a Reflection Coach may propose changing."""

    AGENTS_MD = "agents_md"
    SKILL = "skill"
    TOOL_DESCRIPTION = "tool_description"


@dataclass(frozen=True)
class TrajectoryRef:
    """A persisted run and the task whose trajectory it records."""

    run_id: str
    task_id: str

    def __post_init__(self) -> None:
        for value, label in ((self.run_id, "run id"), (self.task_id, "task id")):
            if not value.strip():
                raise ValueError(f"trajectory reference {label} must not be blank")


@dataclass(frozen=True)
class ReflectionProposalTarget:
    """A revision-pinned surface the proposal changes."""

    kind: ReflectionTargetKind
    owner_employee_id: str
    target_id: str
    target_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, ReflectionTargetKind):
            raise ValueError("reflection proposal target kind must be a ReflectionTargetKind")
        for value, label in (
            (self.owner_employee_id, "target owner employee id"),
            (self.target_id, "target id"),
            (self.target_revision, "target revision"),
        ):
            if not value.strip():
                raise ValueError(f"reflection proposal {label} must not be blank")


@dataclass(frozen=True)
class ReflectionProposal:
    """A proposal-only artifact anchored to a completed Reflection Coach run."""

    artifact_id: str
    artifact_revision_id: str
    target: ReflectionProposalTarget
    diff: str
    rationale: str
    trajectory_refs: tuple[TrajectoryRef, ...]
    evidence_artifact_revision_ids: tuple[str, ...]
    source_routine_run_id: str
    source_run_id: str
    source_employee_id: str
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.artifact_id, "artifact id"),
            (self.artifact_revision_id, "artifact revision id"),
            (self.source_routine_run_id, "source routine run id"),
            (self.source_run_id, "source run id"),
            (self.source_employee_id, "source employee id"),
        ):
            if not value.strip():
                raise ValueError(f"reflection proposal {label} must not be blank")
        if not self.rationale.strip():
            raise ValueError("reflection proposal rationale must not be blank")
        _validate_unified_diff(self.diff)
        if self.source_employee_id == self.target.owner_employee_id:
            raise ValueError("reflection proposal must not target its source employee")
        if len(self.trajectory_refs) < 2:
            raise ValueError("reflection proposal requires at least two distinct trajectory references")
        if len(self.trajectory_refs) != len(set(self.trajectory_refs)):
            raise ValueError("reflection proposal trajectory references must not contain duplicates")
        if any(not evidence_id.strip() for evidence_id in self.evidence_artifact_revision_ids):
            raise ValueError("reflection proposal evidence references must not be blank")
        if len(self.evidence_artifact_revision_ids) != len(set(self.evidence_artifact_revision_ids)):
            raise ValueError("reflection proposal evidence references must not contain duplicates")


def _validate_unified_diff(diff: str) -> None:
    if not diff.strip():
        raise ValueError("reflection proposal diff must not be empty")
    lines = diff.splitlines()
    if (
        len(lines) < 4
        or not lines[0].startswith("--- ")
        or not lines[0][4:].strip()
        or not lines[1].startswith("+++ ")
        or not lines[1][4:].strip()
        or not any(line.startswith("@@ ") for line in lines[2:])
        or not any(
            line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
            for line in lines[2:]
        )
    ):
        raise ValueError("reflection proposal diff must be a unified patch")


__all__ = ["ReflectionProposal", "ReflectionProposalTarget", "ReflectionTargetKind", "TrajectoryRef"]
