"""fire_routine pins the revision it fired under (spec 13 §2.3/§3.3, M4 S2).

The engine is unchanged except for two reads: a firing stamps the routine's live
``latest_revision_id`` on its ``routine_run`` and sources the spawned task's intent from that pinned
revision. The point is the **in-flight invariant**: revising a routine after a run has fired never
re-judges that run — its pin and its spawned task keep the definition they fired under.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from chorus.cron._fire import fire_routine
from chorus.cron._revise import revise_routine
from chorus.ledger import SqliteLedger
from chorus.ledger._models import (
    Routine,
    RoutineConcurrency,
    RoutineRevision,
    RoutineTrigger,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime.fromisoformat("2026-06-16T12:00:00+00:00")
_LATER = datetime.fromisoformat("2026-06-16T13:00:00+00:00")


def _seed(
    ledger: SqliteLedger,
    *,
    intent: str = "v1",
    concurrency: RoutineConcurrency = RoutineConcurrency.ALWAYS,
    next_run_at: datetime = _NOW,
) -> RoutineTrigger:
    """A revisioned routine (sitting at revision 1) + its due cron trigger."""
    ledger.employees.create(Employee(id="e1", name="Ada", role="pm"))
    ledger.routines.create(
        Routine(id="r1", employee_id="e1", intent_template=intent, concurrency_policy=concurrency)
    )
    rev1 = ledger.routine_revisions.append(
        RoutineRevision(
            id="rrev1", routine_id="r1", revision_no=1,
            intent_template=intent, concurrency_policy=concurrency,  # rev1 mirrors the routine
        )
    )
    ledger.routines.set_head("r1", rev1)
    return ledger.routine_triggers.create(
        RoutineTrigger(id="t1", routine_id="r1", cron_expression="0 * * * *", next_run_at=next_run_at)
    )


def test_fire_pins_the_head_revision_and_sources_intent_from_it() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        _seed(ledger, intent="v1")
        task_id = fire_routine(ledger, ledger.routine_triggers.get("t1"), now=_NOW)
        assert task_id is not None

        (run,) = ledger.routine_runs.by_routine("r1")
        assert run.routine_revision_id == "rrev1"  # pinned to the live head
        task = ledger.tasks.get(task_id)
        assert task is not None and task.intent == "v1"  # intent from the pinned revision
    finally:
        ledger.close()


def test_an_inflight_edit_never_rejudges_a_recorded_firing() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        trigger = _seed(ledger, intent="v1")
        first_task = fire_routine(ledger, trigger, now=_NOW)
        assert first_task is not None

        # The manager edits the routine while the first firing is in flight.
        rev2 = revise_routine(ledger, routine_id="r1", revised_by="e1", intent_template="v2")
        assert rev2.revision_no == 2

        # The already-recorded run + its task keep the definition they fired under.
        (run1,) = ledger.routine_runs.by_routine("r1")
        assert run1.routine_revision_id == "rrev1"
        assert ledger.tasks.get(first_task).intent == "v1"  # type: ignore[union-attr]

        # The next firing picks up the new head.
        second_task = fire_routine(ledger, ledger.routine_triggers.get("t1"), now=_LATER)
        assert second_task is not None
        second = ledger.tasks.get(second_task)
        assert second is not None and second.intent == "v2"
        run2 = next(r for r in ledger.routine_runs.by_routine("r1") if r.id != run1.id)
        assert run2.routine_revision_id == rev2.id
    finally:
        ledger.close()
