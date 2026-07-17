"""reconcile_declared_routines — a plugin's declared routines → real routines (spec 13 §5.2).

Role-agnostic and idempotent. For each :class:`~chorus.roles.RoutineDeclaration`, upsert by
``(employee_id, routine_key)``: create the routine (+ revision 1 + trigger) if absent, revise it if
its definition drifted, leave it untouched on a no-op. The function never names a role — registering a
new role plugin that declares routines therefore schedules recurring work with **zero kernel change**.
It is the shared entry point ``Chorus.hire`` calls (and, later, portability import will re-call).

Scoped for v1: a changed *schedule* on an already-existing routine is **not** re-pointed at its trigger
(revisions cover intent/policies/env, not the cron edge). New routines get the right schedule; cadence
changes to existing ones land when re-resolution arrives with S7 portability.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from chorus.cron._add import add_routine
from chorus.cron._revise import NoRoutineRevision, revise_routine

if TYPE_CHECKING:
    from chorus.ledger import Ledger
    from chorus.roles import RoutineDeclaration


@dataclass(frozen=True)
class ReconcileResult:
    """What a reconcile did, by ``routine_key`` (Paperclip's resolution states, trimmed to v1)."""

    created: tuple[str, ...] = field(default_factory=tuple)
    revised: tuple[str, ...] = field(default_factory=tuple)
    unchanged: tuple[str, ...] = field(default_factory=tuple)


def reconcile_declared_routines(
    ledger: Ledger,
    *,
    employee_id: str,
    declarations: Sequence[RoutineDeclaration],
) -> ReconcileResult:
    """Upsert ``declarations`` for ``employee_id`` by ``routine_key`` (idempotent)."""
    created: list[str] = []
    revised: list[str] = []
    unchanged: list[str] = []
    for decl in declarations:
        existing = ledger.routines.by_key(employee_id, decl.routine_key)
        if existing is None:
            add_routine(
                ledger,
                employee_id=employee_id,
                intent_template=decl.intent_template,
                schedule=decl.schedule,
                target=decl.target,
                concurrency=decl.concurrency,
                catch_up=decl.catch_up,
                env=decl.env,
                routine_key=decl.routine_key,
            )
            created.append(decl.routine_key)
            continue
        try:
            # The owner reconciles their own routine, so the owner-authority guard passes.
            revise_routine(
                ledger,
                routine_id=existing.id,
                revised_by=employee_id,
                intent_template=decl.intent_template,
                target=decl.target,
                concurrency=decl.concurrency,
                catch_up=decl.catch_up,
                env=decl.env,
            )
            revised.append(decl.routine_key)
        except NoRoutineRevision:
            unchanged.append(decl.routine_key)  # definition already matches — nothing to do
    return ReconcileResult(tuple(created), tuple(revised), tuple(unchanged))


__all__ = ["ReconcileResult", "reconcile_declared_routines"]
