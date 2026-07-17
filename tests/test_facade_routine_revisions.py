"""Facade routine-revision surface (spec 13 §2/§3, M4 S2) — add creates rev1; revise / restore.

End-to-end through ``org.routines``: adding a routine now seeds revision 1 (the view reports
``latest_revision_no``); ``revise`` advances the live head and ``restore`` rolls back to an earlier
revision through a new head. Authority (owner / owner's manager) is enforced at the boundary.
"""

from __future__ import annotations

import pytest

from chorus.cron import RoutineRevisionAuthorityError
from chorus.facade import Caps, Chorus
from chorus.ledger import Ledger
from chorus.observability import LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger
from chorus.workforce import LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: Ledger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def _org(ledger: Ledger) -> Chorus:
    chorus = _chorus(ledger)
    chorus.hire(name="Moe", role="frontend_engineer")
    chorus.hire(name="Ada", role="pm", reports_to="moe")
    return chorus


def test_add_seeds_revision_one() -> None:
    ledger = open_test_ledger()
    try:
        chorus = _org(ledger)
        view = chorus.routines.add(
            employee="Ada",
            intent_template="weekly plan",
            schedule="0 9 * * 1",
            routine_key="weekly-planning",
        )
        assert view.latest_revision_no == 1
        stored = ledger.routines.get(view.id)
        assert stored is not None and stored.routine_key == "weekly-planning"
        head = ledger.routine_revisions.head(view.id)
        assert head is not None
        assert stored.latest_revision_id == head.id
        assert head.intent_template == "weekly plan"  # rev1 snapshots the definition
    finally:
        ledger.close()


def test_revise_then_restore_through_the_facade() -> None:
    ledger = open_test_ledger()
    try:
        chorus = _org(ledger)
        view = chorus.routines.add(employee="Ada", intent_template="v1", schedule="0 9 * * 1")

        revised = chorus.routines.revise(view.id, by="Ada", intent_template="v2")
        assert revised.latest_revision_no == 2
        assert revised.intent_template == "v2"

        # the owner's manager rolls it back to revision 1 (new head, no history mutation)
        restored = chorus.routines.restore(view.id, revision_no=1, by="Moe")
        assert restored.latest_revision_no == 3
        assert restored.intent_template == "v1"
        assert [r.revision_no for r in ledger.routine_revisions.by_routine(view.id)] == [1, 2, 3]
    finally:
        ledger.close()


def test_a_stranger_may_not_revise() -> None:
    ledger = open_test_ledger()
    try:
        chorus = _org(ledger)
        chorus.hire(name="Eve", role="pm")
        view = chorus.routines.add(employee="Ada", intent_template="v1", schedule="0 9 * * 1")
        with pytest.raises(RoutineRevisionAuthorityError):
            chorus.routines.revise(view.id, by="Eve", intent_template="v2")
    finally:
        ledger.close()
