"""RoutineRevisionRepo + the routine head pointer + the run pin (spec 13 §2, M4 S2).

The revision history is the unit of edit: ``append`` writes an immutable row, ``head`` is the live
definition, and a routine's ``latest_revision_id`` is advanced atomically by ``set_head``. A
``routine_run`` records which revision it fired under. These pin the persistence contract the
revise/restore lifecycle and the firing engine build on.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger
from chorus.ledger._models import (
    Routine,
    RoutineRevision,
    RoutineRun,
    RoutineRunStatus,
    RoutineTrigger,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.unit


def _seed(ledger: Ledger) -> Ledger:
    ledger.employees.create(Employee(id=uid("e1"), name="Ada", role="pm"))
    return ledger


def test_create_persists_env_and_routine_key(ledger: Ledger) -> None:
    _seed(ledger)
    try:
        ledger.routines.create(
            Routine(
                id=uid("r1"),
                employee_id=uid("e1"),
                intent_template="weekly plan",
                env={"GITHUB_TOKEN": "ref:github_token"},
                routine_key="weekly-planning",
            )
        )
        got = ledger.routines.get(uid("r1"))
        assert got is not None
        assert got.env == {"GITHUB_TOKEN": "ref:github_token"}
        assert got.routine_key == "weekly-planning"
    finally:
        ledger.close()


def test_append_get_head_and_by_no(ledger: Ledger) -> None:
    _seed(ledger)
    try:
        ledger.routines.create(Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="v1"))
        rev1 = ledger.routine_revisions.append(
            RoutineRevision(
                id=uid("rev1"), routine_id=uid("r1"), revision_no=1, intent_template="v1"
            )
        )
        rev2 = ledger.routine_revisions.append(
            RoutineRevision(
                id=uid("rev2"), routine_id=uid("r1"), revision_no=2, intent_template="v2"
            )
        )
        assert ledger.routine_revisions.get(uid("rev1")) == rev1
        assert ledger.routine_revisions.get_by_no(uid("r1"), 2) == rev2
        assert [r.id for r in ledger.routine_revisions.by_routine(uid("r1"))] == [
            uid("rev1"),
            uid("rev2"),
        ]
        assert ledger.routine_revisions.head(uid("r1")).id == uid("rev2")  # newest revision_no
    finally:
        ledger.close()


def test_revision_no_is_unique_per_routine(ledger: Ledger) -> None:
    _seed(ledger)
    try:
        ledger.routines.create(Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="v1"))
        ledger.routine_revisions.append(
            RoutineRevision(
                id=uid("rev1"), routine_id=uid("r1"), revision_no=1, intent_template="v1"
            )
        )
        with pytest.raises(Exception):
            ledger.routine_revisions.append(
                RoutineRevision(
                    id=uid("rev1b"), routine_id=uid("r1"), revision_no=1, intent_template="dup"
                )
            )
    finally:
        ledger.close()


def test_set_head_advances_the_pointer_and_mirrors_the_definition(ledger: Ledger) -> None:
    _seed(ledger)
    try:
        ledger.routines.create(
            Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="v1", latest_revision_no=1)
        )
        rev2 = ledger.routine_revisions.append(
            RoutineRevision(
                id=uid("rev2"), routine_id=uid("r1"), revision_no=2, intent_template="v2"
            )
        )
        ledger.routines.set_head(uid("r1"), rev2)
        got = ledger.routines.get(uid("r1"))
        assert got is not None
        assert got.latest_revision_id == uid("rev2")
        assert got.latest_revision_no == 2
        assert got.intent_template == "v2"  # the row mirrors the head's definition
    finally:
        ledger.close()


def test_routine_run_records_the_pinned_revision(ledger: Ledger) -> None:
    _seed(ledger)
    try:
        ledger.routines.create(Routine(id=uid("r1"), employee_id=uid("e1"), intent_template="v1"))
        ledger.routine_triggers.create(RoutineTrigger(id=uid("t1"), routine_id=uid("r1")))
        ledger.routine_revisions.append(
            RoutineRevision(
                id=uid("rev1"), routine_id=uid("r1"), revision_no=1, intent_template="v1"
            )
        )
        ledger.routine_runs.record(
            RoutineRun(
                id=uid("rr1"),
                routine_id=uid("r1"),
                trigger_id=uid("t1"),
                status=RoutineRunStatus.RECEIVED,
                routine_revision_id=uid("rev1"),
            )
        )
        got = ledger.routine_runs.get(uid("rr1"))
        assert got is not None
        assert got.routine_revision_id == uid("rev1")
    finally:
        ledger.close()
