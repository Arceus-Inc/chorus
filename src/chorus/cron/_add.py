"""add_routine — the create path for a routine (spec 13 §3.1).

Shared by the facade (``org.routines.add``, after resolving a slug to an employee id) and the plugin
reconciler (which already holds the id). One write unit: fail-closed env guard → parse the cron (so a
bad schedule leaves no orphan) → routine + revision 1 + cron trigger. Revision 1 is the live head a
firing pins against (spec 13 §2).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from chorus.cron._routine import parse_cron
from chorus.ids import mint_id
from chorus.ledger import (
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineRevision,
    RoutineTarget,
    RoutineTrigger,
    TriggerKind,
)
from chorus.trust import assert_no_inline_secrets

if TYPE_CHECKING:
    from chorus.ledger import SqliteLedger


def add_routine(
    ledger: SqliteLedger,
    *,
    employee_id: str,
    intent_template: str,
    schedule: str,
    target: RoutineTarget = RoutineTarget.SPAWN_TASK,
    concurrency: RoutineConcurrency = RoutineConcurrency.COALESCE,
    catch_up: RoutineCatchUp = RoutineCatchUp.SKIP_MISSED,
    env: dict[str, str] | None = None,
    routine_key: str | None = None,
    timezone: str = "UTC",
) -> Routine:
    """Create a routine owned by ``employee_id``, seed its revision 1, and add its due cron trigger.

    The cron is parsed *before* any write, so a bad schedule (or an inline secret in ``env``) leaves
    no orphan routine. The caller is responsible for having validated that ``employee_id`` exists."""
    assert_no_inline_secrets(env)  # fail-closed: env binds refs, never raw secrets (spec 13 §3)
    next_run_at = parse_cron(schedule, base=datetime.now(UTC), timezone=timezone)

    routine = ledger.routines.create(
        Routine(
            id=mint_id("routine"),
            employee_id=employee_id,
            intent_template=intent_template,
            target=target,
            concurrency_policy=concurrency,
            catch_up_policy=catch_up,
            env=env,
            routine_key=routine_key,
        )
    )
    rev1 = ledger.routine_revisions.append(
        RoutineRevision(
            id=mint_id("rrev"),
            routine_id=routine.id,
            revision_no=1,
            intent_template=intent_template,
            target=target,
            concurrency_policy=concurrency,
            catch_up_policy=catch_up,
            env=env,
            change_summary="created",
        )
    )
    ledger.routines.set_head(routine.id, rev1)
    ledger.routine_triggers.create(
        RoutineTrigger(
            id=mint_id("trig"),
            routine_id=routine.id,
            kind=TriggerKind.CRON,
            cron_expression=schedule,
            timezone=timezone,
            next_run_at=next_run_at,
        )
    )
    refreshed = ledger.routines.get(routine.id)
    assert refreshed is not None  # just created in this transaction
    return refreshed


__all__ = ["add_routine"]
