"""revise_routine / restore_routine — the audited routine-edit path (spec 13 §2.2/§3.2).

A routine's definition is versioned like a §1 DoD: an edit writes a new immutable ``routine_revision``
(``revision_no = head + 1``) and advances the live head; a restore copies an earlier revision into a
new head, recording its provenance and never mutating history. A no-op revise raises
:class:`NoRoutineRevision` so the §6 plugin reconciler stays idempotent. Authority mirrors §1: only
the routine's owner or the owner's manager may edit it. The firing engine pins the revision a run
fired under (§3.3), so an edit never re-judges work in flight.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, cast

from chorus.ids import mint_id
from chorus.ledger._models import (
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRevision,
    RoutineTarget,
)
from chorus.trust import assert_no_inline_secrets

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger

# Sentinel distinguishing "env not supplied" from "env explicitly cleared to None" in a patch.
_UNSET: Final = object()


class NoRoutineRevision(RuntimeError):
    """Nothing to revise — the routine is absent, the target revision is missing, or the patch is a no-op."""


class RoutineRevisionAuthorityError(RuntimeError):
    """The reviser is neither the routine's owner nor the owner's manager (spec 13 §3.2)."""


def revise_routine(
    ledger: SqliteLedger,
    *,
    routine_id: str,
    revised_by: str,
    intent_template: str | None = None,
    target: RoutineTarget | None = None,
    concurrency: RoutineConcurrency | None = None,
    catch_up: RoutineCatchUp | None = None,
    env: object = _UNSET,
    change_summary: str | None = None,
) -> RoutineRevision:
    """Write a new head revision from the current head overlaid with the given patch.

    Only the supplied fields change; the rest carry from the head. Raises :class:`NoRoutineRevision`
    if the routine is unknown or the patch leaves the definition unchanged."""
    routine = ledger.routines.get(routine_id)
    if routine is None:
        raise NoRoutineRevision(f"routine {routine_id!r} does not exist")
    _require_authority(ledger, routine.employee_id, revised_by)
    base = _head(ledger, routine_id)

    new_env = base.env if env is _UNSET else cast("dict[str, str] | None", env)
    assert_no_inline_secrets(new_env)  # fail-closed: env binds refs, never raw secrets (spec 13 §3)
    proposed = RoutineRevision(
        id=mint_id(),
        routine_id=routine_id,
        revision_no=routine.latest_revision_no + 1,
        intent_template=intent_template if intent_template is not None else base.intent_template,
        target=target if target is not None else base.target,
        concurrency_policy=concurrency if concurrency is not None else base.concurrency_policy,
        catch_up_policy=catch_up if catch_up is not None else base.catch_up_policy,
        env=new_env,
        change_summary=change_summary,
    )
    if _same_definition(proposed, base):
        raise NoRoutineRevision(f"the proposed definition for routine {routine_id!r} is unchanged")
    return _commit_head(ledger, routine_id, proposed)


def restore_routine(
    ledger: SqliteLedger, *, routine_id: str, revision_no: int, revised_by: str
) -> RoutineRevision:
    """Copy ``revision_no`` into a *new* head revision (provenance recorded; history never mutated)."""
    routine = ledger.routines.get(routine_id)
    if routine is None:
        raise NoRoutineRevision(f"routine {routine_id!r} does not exist")
    _require_authority(ledger, routine.employee_id, revised_by)

    source = ledger.routine_revisions.get_by_no(routine_id, revision_no)
    if source is None:
        raise NoRoutineRevision(f"routine {routine_id!r} has no revision {revision_no}")

    restored = RoutineRevision(
        id=mint_id(),
        routine_id=routine_id,
        revision_no=routine.latest_revision_no + 1,
        intent_template=source.intent_template,
        target=source.target,
        concurrency_policy=source.concurrency_policy,
        catch_up_policy=source.catch_up_policy,
        env=source.env,
        change_summary=f"restored from revision {revision_no}",
        restored_from_revision_id=source.id,
    )
    return _commit_head(ledger, routine_id, restored)


def _commit_head(
    ledger: SqliteLedger, routine_id: str, revision: RoutineRevision
) -> RoutineRevision:
    """Append the revision and make it the live head (definition mirror + pointer)."""
    appended = ledger.routine_revisions.append(revision)
    ledger.routines.set_head(routine_id, appended)
    return appended


def _head(ledger: SqliteLedger, routine_id: str) -> RoutineRevision:
    """The live head revision. Every routine has a revision 1 (synthesized by migration 0019 or
    written by ``add_routine``), so a missing head is a broken invariant, not a normal case."""
    head = ledger.routine_revisions.head(routine_id)
    if head is None:
        raise NoRoutineRevision(f"routine {routine_id!r} has no revision history")
    return head


def _same_definition(a: RoutineRevision, b: RoutineRevision) -> bool:
    return (
        a.intent_template == b.intent_template
        and a.target is b.target
        and a.concurrency_policy is b.concurrency_policy
        and a.catch_up_policy is b.catch_up_policy
        and a.env == b.env
    )


def _require_authority(ledger: SqliteLedger, owner_id: str, revised_by: str) -> None:
    """The owner may edit their own routine; otherwise the editor must be the owner's manager."""
    if revised_by == owner_id:
        return
    owner = ledger.employees.get(owner_id)
    manager_id = owner.reports_to if owner is not None else None
    if manager_id is None or revised_by != manager_id:
        raise RoutineRevisionAuthorityError(
            f"{revised_by!r} may not revise routine owned by {owner_id!r} "
            f"(only the owner or {manager_id!r} may)"
        )


__all__ = [
    "NoRoutineRevision",
    "RoutineRevisionAuthorityError",
    "restore_routine",
    "revise_routine",
]
