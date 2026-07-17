"""Decomposition orchestration — exact-once manager fan-out (spec 02 §4).

:func:`decompose` ties spec 01's durable primitives together into the manager-splits-work
flow: open-or-resume the ``decomposition_claim`` keyed on
``(source_task_id, accepted_plan_revision_id)``, then for each child — one transaction each
via :meth:`SqliteLedger.create_child` — set ``parent_id``, inherit the source goal, bump
``request_depth``/``depth``, and (when the child *gates* the parent) add a first-class
``task_dependency`` of the parent. Sealing the claim ends the manager's run; it never blocks
awaiting children (re-invocation is the ``children_done`` push, fired by ``finalize_beat``).

The whole flow is **resumable**: a run that dies mid-fan-out re-enters with the same
fingerprint, :meth:`create_child` skips children already recorded, and the gating
``dependencies.add`` is idempotent — so the partial result is reused, never restarted and
never double-fanned-out (spec 02 §4.2).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from chorus.ids import mint_id
from chorus.ledger._models import (
    ActivityVerb,
    DecompositionClaim,
    DecompositionStatus,
    RecoveryAction,
    RecoveryKind,
    Task,
    TaskStatus,
)
from chorus.lifecycle._audit import record_activity

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

# The delegation depth cap (spec 06 §4): the default number of hops from the intake root a manager
# recursion may fan out. Mirrored by ``Caps.request_depth_cap`` (the per-workforce override).
DEFAULT_REQUEST_DEPTH_CAP = 5

# The typed recovery a depth-cap breach opens (spec 02 §6 cause/fingerprint).
_DEPTH_EXCEEDED_CAUSE = "request_depth_exceeded"
_DEPTH_FINGERPRINT = "request_depth"


@dataclass(frozen=True)
class Fanned:
    """The decomposition fanned out exactly once — the sealed claim."""

    claim: DecompositionClaim


@dataclass(frozen=True)
class DepthCapped:
    """The decomposition was refused — it would exceed the delegation depth cap (spec 06 §4).

    No children are created; the source is set ``blocked`` and ``recovery`` is the typed
    ``recovery_action`` (``cause='request_depth_exceeded'``) naming the manager as owner.
    """

    recovery: RecoveryAction


DecompositionOutcome = Fanned | DepthCapped


@dataclass(frozen=True)
class ChildSpec:
    """A child to fan out, plus whether completing it must gate the parent (spec 02 §4.3).

    ``task`` carries the caller's intent/assignee/origin; :func:`decompose` overwrites the
    *structural* fields (``parent_id``, ``goal_id``, ``depth``, ``request_depth``) from the
    source so the work-breakdown is always correct regardless of how the spec was built.
    ``gates_parent`` makes the child a first-class blocker of the parent — *parent-waits-on-
    child is a dependency, not ``parent_id``* (spec 02 §4.3).
    """

    task: Task
    gates_parent: bool = False


def decompose(
    ledger: SqliteLedger,
    *,
    source_task_id: str,
    accepted_plan_revision_id: str,
    children: Sequence[ChildSpec],
    owner_run_id: str | None = None,
    request_fingerprint: str = "",
    request_depth_cap: int = DEFAULT_REQUEST_DEPTH_CAP,
) -> DecompositionOutcome:
    """Fan ``source_task_id`` out into ``children`` exactly once (spec 02 §4, spec 06 §4).

    Returns :class:`Fanned` with the sealed claim on success. If the children would exceed the
    delegation depth cap, returns :class:`DepthCapped` instead — **fails closed**: no children are
    created, the source is set ``blocked``, and a typed ``recovery_action`` is opened. Idempotent on
    retry (resumes the existing claim / recovery). Raises ``KeyError`` if the source does not exist.
    """
    source = ledger.tasks.get(source_task_id)
    if source is None:
        raise KeyError(source_task_id)

    # Delegation depth cap (spec 06 §4): every child inherits request_depth + 1. Check *before* the
    # claim opens, so a breach leaves no partial fan-out to reconcile.
    if source.request_depth + 1 > request_depth_cap:
        return _fail_closed(ledger, source, cap=request_depth_cap)

    claim = ledger.decomposition_claims.by_source_revision(
        source_task_id, accepted_plan_revision_id
    )
    if claim is not None and claim.status is DecompositionStatus.COMPLETED:
        return Fanned(claim)  # already fully fanned out — exact-once, nothing left to do
    if claim is None:
        claim = ledger.decomposition_claims.open(
            DecompositionClaim(
                id=mint_id(),
                source_task_id=source_task_id,
                accepted_plan_revision_id=accepted_plan_revision_id,
                owner_run_id=owner_run_id,
                request_fingerprint=request_fingerprint,
                requested_children=[
                    {"task_id": spec.task.id, "gates_parent": spec.gates_parent}
                    for spec in children
                ],
            )
        )

    # One transaction per child (durable partial result), so a mid-fan-out crash resumes cleanly.
    for spec in children:
        child = replace(
            spec.task,
            parent_id=source.id,
            goal_id=source.goal_id,
            depth=source.depth + 1,
            request_depth=source.request_depth + 1,
        )
        ledger.create_child(claim.id, child)  # idempotent: skips an already-recorded child
        if spec.gates_parent:
            ledger.dependencies.add(source.id, child.id)  # idempotent on the (task, dep) edge

    ledger.decomposition_claims.complete(claim.id)
    sealed = ledger.decomposition_claims.get(claim.id)
    if sealed is None:  # completed above in this call — a missing claim means the store is corrupt
        raise RuntimeError(f"decomposition claim {claim.id} vanished immediately after complete()")
    # Governance audit (spec 08 §5): the manager split this task into a child tree.
    record_activity(
        ledger,
        verb=ActivityVerb.DECOMPOSED,
        subject_id=source_task_id,
        actor_employee_id=source.assignee_employee_id,
        payload={"children": [spec.task.id for spec in children], "claim_id": sealed.id},
    )
    return Fanned(sealed)


def _fail_closed(ledger: SqliteLedger, source: Task, *, cap: int) -> DepthCapped:
    """Refuse the decomposition: block the source + open (or reuse) its depth-cap recovery."""
    ledger.tasks.set_status(source.id, TaskStatus.BLOCKED)
    existing = ledger.recovery_actions.active_for_source(source.id)
    if existing is not None:
        return DepthCapped(existing)  # already surfaced — a retry must not double-open
    recovery = ledger.recovery_actions.open(
        RecoveryAction(
            id=mint_id(),
            source_task_id=source.id,
            kind=RecoveryKind.STRANDED,
            owner_employee_id=source.assignee_employee_id,
            cause=_DEPTH_EXCEEDED_CAUSE,
            fingerprint=_DEPTH_FINGERPRINT,
            evidence={"request_depth": source.request_depth, "cap": cap},
        )
    )
    return DepthCapped(recovery)


__all__ = [
    "ChildSpec",
    "DepthCapped",
    "Fanned",
    "decompose",
]
