"""CapabilityService — the manager's ledger-mutating capabilities (M3, spec 06 §4).

A manager beat's capability tools (``decompose`` for M3 Slice 1) reach the ledger through here. This is
the **dream-free seam**: the dream tool envelope unwraps to a plain method call on this service, so the
mutation logic is testable without a model in the loop.

It wraps the exact-once :func:`~chorus.lifecycle._decompose.decompose` lifecycle plus assignment with
the M3 idempotency rule — child ids are **deterministic per ``(parent, label)``**. A generator that
re-fires the same tool within a beat therefore produces the same children, and the underlying claim +
``create_child`` skip make the second pass a no-op.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chorus.ledger._models import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    OriginKind,
    Task,
    TaskStatus,
)
from chorus.lifecycle._coordination import assign_task
from chorus.lifecycle._decompose import ChildSpec, DepthCapped, decompose

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


@dataclass(frozen=True)
class ChildPlan:
    """One child a manager wants to fan out: a stable ``label``, its ``intent``, an optional assignee,
    and ``depends_on`` sibling labels (edges within this wave, resolved to ids by the service)."""

    label: str
    intent: str
    assignee: str | None = None
    depends_on: tuple[str, ...] = ()


@dataclass(frozen=True)
class DecomposeResult:
    """The outcome of a decompose call: the ``label → task_id`` map, or a fail-closed reason.

    Exactly one of the failure fields is set on a rejection (and ``child_ids`` is empty): ``depth_capped``
    when the fan-out would exceed the delegation depth cap, or ``unknown_assignees`` when a child names a
    report that is not a direct report employee. A clean fan-out leaves both empty and ``child_ids`` populated.
    """

    child_ids: dict[str, str] = field(default_factory=dict)
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()


@dataclass(frozen=True)
class SubmitTaskResult:
    """The outcome of a manager submitting one follow-up child task."""

    child_id: str | None = None
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignTaskResult:
    """The outcome of a manager re-routing one existing child task."""

    assigned: bool = False
    unknown_assignee: str | None = None
    not_child: bool = False
    terminal_or_missing: bool = False


def _child_id(parent_id: str, label: str) -> str:
    """A deterministic child id per ``(parent, label)`` so a re-fired decompose never duplicates."""
    digest = hashlib.sha1(f"{parent_id}::{label}".encode()).hexdigest()[:12]
    return f"task_{digest}"


class CapabilityService:
    """Ledger-mutating capabilities a manager beat invokes (``decompose`` for M3 Slice 1)."""

    def __init__(self, ledger: SqliteLedger) -> None:
        self._ledger = ledger

    def decompose(
        self, *, parent_id: str, revision: str, children: Sequence[ChildPlan]
    ) -> DecomposeResult:
        """Fan ``parent_id`` into ``children``, assign each, wire sibling deps — idempotent per ``revision``.

        Every child ``gates_parent`` (the parent waits on it via the M2 dependency gate). Returns
        :class:`DecomposeResult` with ``depth_capped=True`` and no children when the fan-out would exceed
        the delegation depth cap — the underlying lifecycle fails closed (parent set ``blocked``).

        ``revision`` is the manager's beat (``run_id``): the decomposition is recorded as the parent's
        accepted plan revision (the claim's exact-once key), so a re-fired tool resumes the same claim.
        """
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        unknown = self._unknown_assignees(children, manager_id=parent.assignee_employee_id)
        if unknown:  # fail closed at the boundary — a bad report id never half-applies a fan-out
            return DecomposeResult(unknown_assignees=unknown)

        plan_revision_id = self._ensure_plan_revision(parent_id, revision)
        ids = {child.label: _child_id(parent_id, child.label) for child in children}
        specs = [
            ChildSpec(
                task=Task(
                    id=ids[child.label],
                    intent=child.intent,
                    status=TaskStatus.TODO,
                    assignee_employee_id=child.assignee,
                    origin_kind=OriginKind.DECOMPOSITION,
                    origin_id=parent_id,
                    origin_fingerprint=child.label,
                ),
                gates_parent=True,  # the parent waits on every child (parent-waits-on-children)
            )
            for child in children
        ]
        outcome = decompose(
            self._ledger,
            source_task_id=parent_id,
            accepted_plan_revision_id=plan_revision_id,
            owner_run_id=self._owner_run_id(revision),
            children=specs,
        )
        if isinstance(outcome, DepthCapped):
            return DecomposeResult(depth_capped=True)

        for child in children:
            if child.assignee is not None:
                assign_task(self._ledger, ids[child.label], child.assignee)
            for blocker_label in child.depends_on:
                self._ledger.dependencies.add(ids[child.label], ids[blocker_label])
        return DecomposeResult(child_ids=ids)

    def submit_one(
        self, *, parent_id: str, revision: str, child: ChildPlan
    ) -> SubmitTaskResult:
        """Submit one incremental child task during an integrate beat.

        This is the manager's bounded "create one follow-up" move. It uses the same exact-once
        decomposition claim machinery as :meth:`decompose`, but with a single child and a revision
        unique to the current manager beat/action.
        """
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        unknown = self._unknown_assignees((child,), manager_id=parent.assignee_employee_id)
        if unknown:
            return SubmitTaskResult(unknown_assignees=unknown)

        child_id = _child_id(parent_id, child.label)
        outcome = decompose(
            self._ledger,
            source_task_id=parent_id,
            accepted_plan_revision_id=self._ensure_plan_revision(parent_id, revision),
            owner_run_id=self._owner_run_id(revision),
            children=(
                ChildSpec(
                    task=Task(
                        id=child_id,
                        intent=child.intent,
                        status=TaskStatus.TODO,
                        assignee_employee_id=child.assignee,
                        origin_kind=OriginKind.DECOMPOSITION,
                        origin_id=parent_id,
                        origin_fingerprint=child.label,
                    ),
                    gates_parent=True,
                ),
            ),
        )
        if isinstance(outcome, DepthCapped):
            return SubmitTaskResult(depth_capped=True)
        if child.assignee is not None:
            assign_task(self._ledger, child_id, child.assignee)
        return SubmitTaskResult(child_id=child_id)

    def reassign(
        self, *, parent_id: str, task_id: str, assignee: str, assigned_by: str | None = None
    ) -> AssignTaskResult:
        """Route one direct child of ``parent_id`` to one of the parent's direct reports."""
        parent = self._ledger.tasks.get(parent_id)
        if parent is None:
            raise KeyError(parent_id)
        if not self._is_direct_report(assignee, manager_id=parent.assignee_employee_id):
            return AssignTaskResult(unknown_assignee=assignee)
        task = self._ledger.tasks.get(task_id)
        if task is None:
            return AssignTaskResult(terminal_or_missing=True)
        if task.parent_id != parent_id:
            return AssignTaskResult(not_child=True)
        if assign_task(self._ledger, task_id, assignee, assigned_by=assigned_by) is None:
            return AssignTaskResult(terminal_or_missing=True)
        return AssignTaskResult(assigned=True)

    def _unknown_assignees(
        self, children: Sequence[ChildPlan], *, manager_id: str | None
    ) -> tuple[str, ...]:
        """Assignees named by ``children`` that are not direct reports — ordered and deduplicated."""
        seen: dict[str, None] = {}
        for child in children:
            if child.assignee is None:
                continue
            if not self._is_direct_report(child.assignee, manager_id=manager_id):
                seen.setdefault(child.assignee, None)
        return tuple(seen)

    def _is_direct_report(self, employee_id: str, *, manager_id: str | None) -> bool:
        employee = self._ledger.employees.get(employee_id)
        return manager_id is not None and employee is not None and employee.reports_to == manager_id

    def _ensure_plan_revision(self, parent_id: str, revision: str) -> str:
        """Record (once per beat) the parent's accepted decomposition plan; return its revision id.

        Idempotent: keyed on ``revision`` (the run_id), so a re-fired tool finds the existing revision
        and skips creation. The artifact anchors the claim's lineage guard to the parent task.
        """
        plan_revision_id = f"planrev_{revision}"
        if self._ledger.artifact_revisions.get(plan_revision_id) is not None:
            return plan_revision_id
        artifact_id = f"plan_{parent_id}__{revision}"
        self._ledger.artifacts.create(
            Artifact(id=artifact_id, task_id=parent_id, type=ArtifactType.DOC)
        )
        self._ledger.artifact_revisions.record(
            ArtifactRevision(
                id=plan_revision_id,
                artifact_id=artifact_id,
                resource_ref={"decompose": revision},
            )
        )
        return plan_revision_id

    def _owner_run_id(self, revision: str) -> str | None:
        """Use ``revision`` as owner only when it is a real run id; tests may use synthetic revisions."""
        return revision if self._ledger.runs.get(revision) is not None else None


__all__ = [
    "AssignTaskResult",
    "CapabilityService",
    "ChildPlan",
    "DecomposeResult",
    "SubmitTaskResult",
]
