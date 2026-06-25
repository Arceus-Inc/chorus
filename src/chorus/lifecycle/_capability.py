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
    ActivityVerb,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    DecompositionStatus,
    DodStatus,
    OriginKind,
    Task,
    TaskStatus,
)
from chorus.lifecycle._audit import record_activity
from chorus.lifecycle._coordination import assign_task
from chorus.lifecycle._decompose import ChildSpec, DepthCapped, decompose
from chorus.outcomes import DoDKind

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
    reviewer_assignees: tuple[str, ...] = ()
    already_decomposed: bool = False


@dataclass(frozen=True)
class SubmitTaskResult:
    """The outcome of a manager submitting one follow-up child task."""

    child_id: str | None = None
    reviewer_assignees: tuple[str, ...] = ()
    depth_capped: bool = False
    unknown_assignees: tuple[str, ...] = ()


@dataclass(frozen=True)
class AssignTaskResult:
    """The outcome of a manager re-routing one existing child task."""

    assigned: bool = False
    unknown_assignee: str | None = None
    not_child: bool = False
    terminal_or_missing: bool = False


@dataclass(frozen=True)
class RecordVerdictResult:
    """The outcome of a reviewer rendering its approve/block verdict on a task's ``agent_review`` DoD.

    A clean record sets ``recorded`` with ``approved`` reflecting the decision. Exactly one fail-closed
    reason is set otherwise: ``not_reviewable`` when the task has no ``agent_review`` DoD to verdict, or
    ``self_review`` when the reviewer is the task's own author (a worker can't verify its own work)."""

    recorded: bool = False
    approved: bool = False
    not_reviewable: bool = False
    self_review: bool = False


# DoD kinds a Reviewer renders a verdict on (an objective ``command`` / a human approval are not).
_REVIEWER_GATED_KINDS = frozenset({DoDKind.AGENT_REVIEW, DoDKind.REVIEWED_BUILD})


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
        reviewers = self._reviewer_assignees(children)
        if reviewers:
            return DecomposeResult(reviewer_assignees=reviewers)
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
        existing_claim = self._ledger.decomposition_claims.by_source_revision(
            parent_id, plan_revision_id
        )
        outcome = decompose(
            self._ledger,
            source_task_id=parent_id,
            accepted_plan_revision_id=plan_revision_id,
            owner_run_id=self._owner_run_id(revision),
            children=specs,
        )
        if isinstance(outcome, DepthCapped):
            return DecomposeResult(depth_capped=True)

        completed_before = (
            existing_claim is not None and existing_claim.status is DecompositionStatus.COMPLETED
        )
        claim_child_ids = set(outcome.claim.child_task_ids)
        requested_child_ids = set(ids.values())
        if not requested_child_ids.issubset(claim_child_ids):
            return DecomposeResult(
                child_ids={
                    f"existing_{index}": child_id
                    for index, child_id in enumerate(outcome.claim.child_task_ids, start=1)
                },
                already_decomposed=True,
            )

        for child in children:
            if child.assignee is not None:
                assign_task(self._ledger, ids[child.label], child.assignee)
            for blocker_label in child.depends_on:
                self._ledger.dependencies.add(ids[child.label], ids[blocker_label])
        return DecomposeResult(child_ids=ids, already_decomposed=completed_before)

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
        reviewers = self._reviewer_assignees((child,))
        if reviewers:
            return SubmitTaskResult(reviewer_assignees=reviewers)
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

    def record_verdict(
        self,
        *,
        task_id: str,
        run_id: str,
        reviewer_id: str,
        approve: bool,
        feedback: str,
        verify_command: str = "",
    ) -> RecordVerdictResult:
        """Record a reviewer's verdict on a task's reviewer-gated DoD (approve→PASSED, block→FAILED).

        The verdict IS the DoD's verdict — it does not itself transition the task. The kernel reads the
        recorded DoD status after the reviewer beat and lands (approve) or routes the block. For a
        ``reviewed_build`` DoD the reviewer also reports ``verify_command`` (the project's verify command
        the kernel then runs); a PASSED here means "quality approved", with the objective run still to
        come. Fails closed on a non reviewer-gated DoD or a reviewer verifying its own work."""
        task = self._ledger.tasks.get(task_id)
        if task is None:
            raise KeyError(task_id)
        dod = self._ledger.dod.get_for_task(task_id)
        if dod is None or DoDKind(dod.kind) not in _REVIEWER_GATED_KINDS:
            return RecordVerdictResult(not_reviewable=True)
        if reviewer_id == task.assignee_employee_id:
            return RecordVerdictResult(self_review=True)
        status = DodStatus.PASSED if approve else DodStatus.FAILED
        verdict: dict[str, object] = {"approve": approve, "feedback": feedback, "reviewer": reviewer_id}
        if verify_command:  # only a reviewed_build carries a command for the kernel to run
            verdict["verify_command"] = verify_command
        self._ledger.dod.record_verdict(dod.id, status, verdict=verdict, run_id=run_id)
        record_activity(
            self._ledger,
            verb=ActivityVerb.REVIEW_VERDICT,
            subject_id=task_id,
            actor_employee_id=reviewer_id,
            payload={"approve": approve, "feedback": feedback},
        )
        return RecordVerdictResult(recorded=True, approved=approve)

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

    def _reviewer_assignees(self, children: Sequence[ChildPlan]) -> tuple[str, ...]:
        """Assignees that are reviewers — ordered and deduplicated.

        A reviewer *reviews* (the kernel auto-dispatches it for a reviewer-gated DoD); it never *owns*
        deliverable work — its role is read-only with a human-approval DoD, so a deliverable routed to
        one would strand. Fail closed so the manager reassigns the work to an engineer."""
        seen: dict[str, None] = {}
        for child in children:
            if child.assignee is None:
                continue
            employee = self._ledger.employees.get(child.assignee)
            if employee is not None and employee.role == "reviewer":
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
