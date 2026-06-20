"""RoutineRevisionRepo + the routine head pointer + the run pin (spec 13 §2, M4 S2).

The revision history is the unit of edit: ``append`` writes an immutable row, ``head`` is the live
definition, and a routine's ``latest_revision_id`` is advanced atomically by ``set_head``. A
``routine_run`` records which revision it fired under. These pin the persistence contract the
revise/restore lifecycle and the firing engine build on.
"""

from __future__ import annotations

import pytest

from chorus.ledger import SqliteLedger
from chorus.ledger._models import (
    Routine,
    RoutineRevision,
    RoutineRun,
    RoutineRunStatus,
    RoutineTrigger,
)
from chorus.workforce import Employee

pytestmark = pytest.mark.unit


def _ledger() -> SqliteLedger:
    ledger = SqliteLedger.open(":memory:")
    ledger.employees.create(Employee(id="e1", name="Ada", role="pm"))
    return ledger


def test_create_persists_env_and_routine_key() -> None:
    ledger = _ledger()
    try:
        ledger.routines.create(
            Routine(
                id="r1",
                employee_id="e1",
                intent_template="weekly plan",
                env={"GITHUB_TOKEN": "ref:github_token"},
                routine_key="weekly-planning",
            )
        )
        got = ledger.routines.get("r1")
        assert got is not None
        assert got.env == {"GITHUB_TOKEN": "ref:github_token"}
        assert got.routine_key == "weekly-planning"
    finally:
        ledger.close()


def test_append_get_head_and_by_no() -> None:
    ledger = _ledger()
    try:
        ledger.routines.create(Routine(id="r1", employee_id="e1", intent_template="v1"))
        rev1 = ledger.routine_revisions.append(
            RoutineRevision(id="rev1", routine_id="r1", revision_no=1, intent_template="v1")
        )
        rev2 = ledger.routine_revisions.append(
            RoutineRevision(id="rev2", routine_id="r1", revision_no=2, intent_template="v2")
        )
        assert ledger.routine_revisions.get("rev1") == rev1
        assert ledger.routine_revisions.get_by_no("r1", 2) == rev2
        assert [r.id for r in ledger.routine_revisions.by_routine("r1")] == ["rev1", "rev2"]
        assert ledger.routine_revisions.head("r1").id == "rev2"  # newest revision_no
    finally:
        ledger.close()


def test_revision_no_is_unique_per_routine() -> None:
    ledger = _ledger()
    try:
        ledger.routines.create(Routine(id="r1", employee_id="e1", intent_template="v1"))
        ledger.routine_revisions.append(
            RoutineRevision(id="rev1", routine_id="r1", revision_no=1, intent_template="v1")
        )
        with pytest.raises(Exception):
            ledger.routine_revisions.append(
                RoutineRevision(id="rev1b", routine_id="r1", revision_no=1, intent_template="dup")
            )
    finally:
        ledger.close()


def test_set_head_advances_the_pointer_and_mirrors_the_definition() -> None:
    ledger = _ledger()
    try:
        ledger.routines.create(
            Routine(id="r1", employee_id="e1", intent_template="v1", latest_revision_no=1)
        )
        rev2 = ledger.routine_revisions.append(
            RoutineRevision(id="rev2", routine_id="r1", revision_no=2, intent_template="v2")
        )
        ledger.routines.set_head("r1", rev2)
        got = ledger.routines.get("r1")
        assert got is not None
        assert got.latest_revision_id == "rev2"
        assert got.latest_revision_no == 2
        assert got.intent_template == "v2"  # the row mirrors the head's definition
    finally:
        ledger.close()


def test_routine_run_records_the_pinned_revision() -> None:
    ledger = _ledger()
    try:
        ledger.routines.create(Routine(id="r1", employee_id="e1", intent_template="v1"))
        ledger.routine_triggers.create(RoutineTrigger(id="t1", routine_id="r1"))
        ledger.routine_revisions.append(
            RoutineRevision(id="rev1", routine_id="r1", revision_no=1, intent_template="v1")
        )
        ledger.routine_runs.record(
            RoutineRun(
                id="rr1",
                routine_id="r1",
                trigger_id="t1",
                status=RoutineRunStatus.RECEIVED,
                routine_revision_id="rev1",
            )
        )
        got = ledger.routine_runs.get("rr1")
        assert got is not None
        assert got.routine_revision_id == "rev1"
    finally:
        ledger.close()
