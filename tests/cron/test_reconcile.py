"""reconcile_declared_routines — plugin declarations → real routines (spec 13 §5.2, M4 S6).

Role-agnostic and idempotent: for each declaration, upsert by (employee_id, routine_key) — create the
routine (+ rev1 + trigger) if absent, revise it if its definition drifted, leave it untouched on a
no-op. The reconciler never names a role; that is what makes "a new role schedules with no kernel
change" literally true. It is the shared entry point hire-time (and, later, portability import) call.
"""

from __future__ import annotations

import pytest

from chorus.cron import reconcile_declared_routines
from chorus.ledger import Ledger
from chorus.roles import RoutineDeclaration
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_DECL = RoutineDeclaration(
    routine_key="weekly-planning", intent_template="file a weekly plan", schedule="0 9 * * 1"
)


def _ledger() -> Ledger:
    ledger = open_test_ledger()
    ledger.employees.create(Employee(id=uid("pm1"), name="Ada", role="pm"))
    return ledger


def test_absent_declaration_is_created() -> None:
    ledger = _ledger()
    try:
        result = reconcile_declared_routines(ledger, employee_id=uid("pm1"), declarations=(_DECL,))
        assert result.created == ("weekly-planning",)
        assert result.revised == () and result.unchanged == ()

        routine = ledger.routines.by_key(uid("pm1"), "weekly-planning")
        assert routine is not None
        assert routine.latest_revision_no == 1
        assert routine.intent_template == "file a weekly plan"
        (trigger,) = ledger.routine_triggers.by_routine(routine.id)
        assert trigger.cron_expression == "0 9 * * 1" and trigger.next_run_at is not None
    finally:
        ledger.close()


def test_reconcile_is_idempotent() -> None:
    ledger = _ledger()
    try:
        reconcile_declared_routines(ledger, employee_id=uid("pm1"), declarations=(_DECL,))
        again = reconcile_declared_routines(ledger, employee_id=uid("pm1"), declarations=(_DECL,))
        assert again.created == () and again.revised == ()
        assert again.unchanged == ("weekly-planning",)

        # exactly one routine, still at revision 1 — no churn
        routine = ledger.routines.by_key(uid("pm1"), "weekly-planning")
        assert routine is not None and routine.latest_revision_no == 1
        assert len(ledger.routines.list(employee_id=uid("pm1"))) == 1
    finally:
        ledger.close()


def test_a_changed_declaration_revises_in_place() -> None:
    ledger = _ledger()
    try:
        reconcile_declared_routines(ledger, employee_id=uid("pm1"), declarations=(_DECL,))
        changed = RoutineDeclaration(
            routine_key="weekly-planning",
            intent_template="file a SHARPER weekly plan",
            schedule="0 9 * * 1",
        )
        result = reconcile_declared_routines(
            ledger, employee_id=uid("pm1"), declarations=(changed,)
        )
        assert result.revised == ("weekly-planning",)

        routine = ledger.routines.by_key(uid("pm1"), "weekly-planning")
        assert routine is not None
        assert routine.latest_revision_no == 2  # a new head, same routine_key
        assert routine.intent_template == "file a SHARPER weekly plan"
    finally:
        ledger.close()
