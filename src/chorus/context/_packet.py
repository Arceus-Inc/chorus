"""Immutable, bounded task-context objects projected from the Chorus ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from dream.contracts.strategy import LandedPhase, RecoveryHint


class AncestryKind(StrEnum):
    GOAL = "goal"
    TASK = "task"


@dataclass(frozen=True)
class Citation:
    """A durable source row named in the rendered briefing."""

    source: str
    detail: str


@dataclass(frozen=True)
class TaskContract:
    intent: str
    dod: tuple[DoDRequirement, ...] = ()


@dataclass(frozen=True)
class DoDRequirement:
    kind: str
    detail: str


@dataclass(frozen=True)
class AncestryLink:
    kind: AncestryKind
    id: str
    title: str
    status: str


@dataclass(frozen=True)
class PriorBeat:
    run_id: str
    phase: LandedPhase
    recovery_hint: RecoveryHint
    evaluator_notes: tuple[str, ...] = ()
    files_touched: tuple[str, ...] = ()
    todo_digest: str = ""
    summary: str = ""
    citation: Citation = field(default_factory=lambda: Citation("", ""))


@dataclass(frozen=True)
class InboxItem:
    id: str
    sender: str
    body: str
    task_id: str | None


@dataclass(frozen=True)
class SiblingFailure:
    task_id: str
    status: str
    notes: tuple[str, ...]
    citation: Citation


@dataclass(frozen=True)
class BudgetPosition:
    spent_cents: int
    limit_cents: int | None
    beat_count: int


@dataclass(frozen=True)
class Truncation:
    section: str
    omitted: int
    reason: str


@dataclass(frozen=True)
class ReportRef:
    """A direct report the employee may name as an assignee."""

    employee_id: str
    role: str
    can_lead: bool = False


@dataclass(frozen=True)
class OperatingEnvironment:
    """Host facts for roles that call ``run_command``."""

    os_label: str
    shell: str
    path_runtimes: tuple[str, ...]


@dataclass(frozen=True)
class LatticeWake:
    """Prior-beat lattice gate teaser. Cookbook steps live in the consolidate skill."""

    gate_open: bool
    teaser: str


@dataclass(frozen=True)
class TaskContextPacket:
    """Task-keyed control-plane context. It never owns Dream conversation state."""

    task_id: str
    contract: TaskContract
    ancestry: tuple[AncestryLink, ...]
    prior_beats: tuple[PriorBeat, ...]
    inbox: tuple[InboxItem, ...]
    sibling_failures: tuple[SiblingFailure, ...]
    budget: BudgetPosition
    citations: tuple[Citation, ...]
    truncation: tuple[Truncation, ...] = ()
    reports: tuple[ReportRef, ...] = ()
    runtime: OperatingEnvironment | None = None
    lattice_wake: LatticeWake | None = None


__all__ = [
    "AncestryKind",
    "AncestryLink",
    "BudgetPosition",
    "Citation",
    "DoDRequirement",
    "InboxItem",
    "LatticeWake",
    "OperatingEnvironment",
    "PriorBeat",
    "ReportRef",
    "SiblingFailure",
    "TaskContextPacket",
    "TaskContract",
    "Truncation",
]
