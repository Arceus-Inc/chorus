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

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from chorus.ledger._models import ActivityVerb, DecompositionClaim, DecompositionStatus, Task
from chorus.lifecycle._audit import record_activity

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


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
) -> DecompositionClaim:
    """Fan ``source_task_id`` out into ``children`` exactly once, returning the sealed claim.

    Idempotent on retry: a second call against the same accepted plan revision resumes the
    existing claim and reuses already-created children. Raises ``KeyError`` if the source
    task does not exist.
    """
    source = ledger.tasks.get(source_task_id)
    if source is None:
        raise KeyError(source_task_id)

    claim = ledger.decomposition_claims.by_source_revision(
        source_task_id, accepted_plan_revision_id
    )
    if claim is not None and claim.status is DecompositionStatus.COMPLETED:
        return claim  # already fully fanned out — exact-once, nothing left to do
    if claim is None:
        claim = ledger.decomposition_claims.open(
            DecompositionClaim(
                id=f"claim_{uuid.uuid4().hex[:12]}",
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
    assert sealed is not None  # just completed it in this call
    # Governance audit (spec 08 §5): the manager split this task into a child tree.
    record_activity(
        ledger,
        verb=ActivityVerb.DECOMPOSED,
        subject_id=source_task_id,
        actor_employee_id=source.assignee_employee_id,
        payload={"children": [spec.task.id for spec in children], "claim_id": sealed.id},
    )
    return sealed


__all__ = [
    "ChildSpec",
    "decompose",
]
