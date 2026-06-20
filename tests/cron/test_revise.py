"""revise_routine / restore_routine — the audited routine-edit path (spec 13 §2.2/§3.2, M4 S2).

A snapshot is the unit of edit: a revise writes a new immutable ``routine_revision`` and advances the
live head; a restore copies an earlier revision into a new head (never mutating history). A no-op
revise is idempotent (so the §6 plugin reconciler can re-run safely). Authority mirrors §1
revise_dod: only the routine's owner or the owner's manager may edit it.
"""

from __future__ import annotations

import pytest

from chorus.cron import (
    NoRoutineRevision,
    RoutineRevisionAuthorityError,
    restore_routine,
    revise_routine,
)
from chorus.ledger import SqliteLedger
from chorus.ledger._models import Routine, RoutineRevision
from chorus.workforce import Employee

pytestmark = pytest.mark.unit


def _ledger() -> SqliteLedger:
    ledger = SqliteLedger.open(":memory:")
    ledger.employees.create(Employee(id="mgr", name="Mo", role="manager"))
    ledger.employees.create(Employee(id="e1", name="Ada", role="pm", reports_to="mgr"))
    ledger.employees.create(Employee(id="x1", name="Eve", role="pm"))
    return ledger


def _seed(ledger: SqliteLedger, *, intent: str = "v1") -> None:
    """A routine r1 owned by e1, sitting at revision 1."""
    ledger.routines.create(Routine(id="r1", employee_id="e1", intent_template=intent))
    rev1 = ledger.routine_revisions.append(
        RoutineRevision(id="rrev1", routine_id="r1", revision_no=1, intent_template=intent)
    )
    ledger.routines.set_head("r1", rev1)


def test_revise_writes_a_new_head_and_mirrors_the_live_definition() -> None:
    ledger = _ledger()
    try:
        _seed(ledger)
        rev = revise_routine(
            ledger, routine_id="r1", revised_by="e1",
            intent_template="v2", change_summary="sharper goal",
        )
        assert rev.revision_no == 2
        assert rev.change_summary == "sharper goal"

        routine = ledger.routines.get("r1")
        assert routine is not None
        assert routine.latest_revision_no == 2
        assert routine.latest_revision_id == rev.id
        assert routine.intent_template == "v2"  # the live row reflects the new head
        # history is intact: both revisions present, oldest first
        assert [r.revision_no for r in ledger.routine_revisions.by_routine("r1")] == [1, 2]
    finally:
        ledger.close()


def test_revise_with_no_change_is_idempotent() -> None:
    ledger = _ledger()
    try:
        _seed(ledger, intent="v1")
        with pytest.raises(NoRoutineRevision):
            revise_routine(ledger, routine_id="r1", revised_by="e1", intent_template="v1")
        # no phantom revision written
        assert [r.revision_no for r in ledger.routine_revisions.by_routine("r1")] == [1]
    finally:
        ledger.close()


def test_revise_unknown_routine_raises() -> None:
    ledger = _ledger()
    try:
        with pytest.raises(NoRoutineRevision):
            revise_routine(ledger, routine_id="nope", revised_by="e1", intent_template="x")
    finally:
        ledger.close()


def test_revise_can_set_and_clear_env() -> None:
    ledger = _ledger()
    try:
        _seed(ledger)
        revise_routine(
            ledger, routine_id="r1", revised_by="e1", env={"TOKEN": "ref:tok"},
        )
        assert ledger.routines.get("r1").env == {"TOKEN": "ref:tok"}  # type: ignore[union-attr]
        revise_routine(ledger, routine_id="r1", revised_by="e1", env=None)
        assert ledger.routines.get("r1").env is None  # type: ignore[union-attr]
    finally:
        ledger.close()


def test_restore_copies_an_earlier_revision_into_a_new_head() -> None:
    ledger = _ledger()
    try:
        _seed(ledger, intent="v1")
        revise_routine(ledger, routine_id="r1", revised_by="e1", intent_template="v2")
        restored = restore_routine(ledger, routine_id="r1", revision_no=1, revised_by="e1")

        assert restored.revision_no == 3  # a NEW head, not a mutation of rev1
        assert restored.intent_template == "v1"  # body copied from revision 1
        assert restored.restored_from_revision_id == "rrev1"

        routine = ledger.routines.get("r1")
        assert routine is not None
        assert routine.latest_revision_no == 3
        assert routine.intent_template == "v1"  # live definition is back to v1
    finally:
        ledger.close()


def test_restore_unknown_revision_raises() -> None:
    ledger = _ledger()
    try:
        _seed(ledger)
        with pytest.raises(NoRoutineRevision):
            restore_routine(ledger, routine_id="r1", revision_no=99, revised_by="e1")
    finally:
        ledger.close()


def test_revise_rejects_an_inline_secret_in_env() -> None:
    from chorus.errors import InvalidIntake

    ledger = _ledger()
    try:
        _seed(ledger)
        with pytest.raises(InvalidIntake, match="inline secret"):
            revise_routine(
                ledger, routine_id="r1", revised_by="e1", env={"GITHUB_TOKEN": "ghp_rawvalue"}
            )
        # fail-closed: nothing written
        assert [r.revision_no for r in ledger.routine_revisions.by_routine("r1")] == [1]
    finally:
        ledger.close()


def test_owner_and_manager_may_revise_but_a_stranger_may_not() -> None:
    ledger = _ledger()
    try:
        _seed(ledger)
        # owner ✓
        revise_routine(ledger, routine_id="r1", revised_by="e1", intent_template="v2")
        # owner's manager ✓
        revise_routine(ledger, routine_id="r1", revised_by="mgr", intent_template="v3")
        # a stranger ✗
        with pytest.raises(RoutineRevisionAuthorityError):
            revise_routine(ledger, routine_id="r1", revised_by="x1", intent_template="v4")
    finally:
        ledger.close()
