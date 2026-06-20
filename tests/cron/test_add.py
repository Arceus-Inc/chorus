"""The kernel-side add_routine helper + RoutineRepo.by_key (spec 13 §3.1, M4 S6).

``add_routine`` is the create path shared by the facade (``org.routines.add``, after slug→id) and the
plugin reconciler (which already has the employee id): env-guard → parse cron → routine + revision 1 +
trigger. ``RoutineRepo.by_key`` is the idempotent lookup the reconciler upserts on.
"""

from __future__ import annotations

import pytest

from chorus.cron import add_routine
from chorus.errors import InvalidIntake
from chorus.ledger import SqliteLedger
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _ledger() -> SqliteLedger:
    ledger = SqliteLedger.open(":memory:")
    ledger.employees.create(Employee(id="e1", name="Ada", role="pm"))
    return ledger


def test_add_routine_seeds_revision_one_and_a_trigger() -> None:
    ledger = _ledger()
    try:
        routine = add_routine(
            ledger,
            employee_id="e1",
            intent_template="weekly plan",
            schedule="0 9 * * 1",
            routine_key="weekly-planning",
        )
        assert routine.latest_revision_no == 1
        assert routine.routine_key == "weekly-planning"
        head = ledger.routine_revisions.head(routine.id)
        assert head is not None and head.intent_template == "weekly plan"
        assert routine.latest_revision_id == head.id
        (trigger,) = ledger.routine_triggers.by_routine(routine.id)
        assert trigger.cron_expression == "0 9 * * 1"
        assert trigger.next_run_at is not None
    finally:
        ledger.close()


def test_add_routine_rejects_an_inline_secret_fail_closed() -> None:
    ledger = _ledger()
    try:
        with pytest.raises(InvalidIntake, match="inline secret"):
            add_routine(
                ledger, employee_id="e1", intent_template="x", schedule="0 9 * * 1",
                env={"API_KEY": "sk-raw"},
            )
        assert ledger.routines.list() == []  # nothing persisted on the failed path
    finally:
        ledger.close()


def test_by_key_finds_the_routine_scoped_to_its_owner() -> None:
    ledger = _ledger()
    try:
        ledger.employees.create(Employee(id="e2", name="Bo", role="pm"))
        add_routine(ledger, employee_id="e1", intent_template="a", schedule="0 9 * * 1",
                    routine_key="weekly")
        add_routine(ledger, employee_id="e2", intent_template="b", schedule="0 9 * * 1",
                    routine_key="weekly")

        found = ledger.routines.by_key("e1", "weekly")
        assert found is not None and found.employee_id == "e1" and found.intent_template == "a"
        assert ledger.routines.by_key("e1", "absent") is None
    finally:
        ledger.close()
