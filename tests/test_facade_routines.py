"""Facade routine surface (spec 13 §3/§7, M4 S1) — add / list / show / pause / resume.

``add_routine`` is the verb that makes recurring work *reachable*: it persists a ``routine`` + its
cron ``routine_trigger`` (the firing engine already exists) and returns a :class:`RoutineView`. The
reads (``routine``/``list_routines``) project through the inspector; ``pause``/``resume`` flip the
firing status. Everything is enum-typed — no stringly policy/status arguments cross the boundary.
"""

from __future__ import annotations

import pytest

from chorus.errors import UnknownEmployee
from chorus.facade import Caps, Chorus
from chorus.ledger import SqliteLedger
from chorus.ledger._models import RoutineConcurrency, RoutineStatus, TriggerKind
from chorus.observability import LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: SqliteLedger) -> Chorus:
    """A facade over a real ledger with a live workforce + inspector (the routine surface needs both)."""
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


def test_add_routine_persists_a_routine_and_its_cron_trigger() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Moe", role="manager")
        view = chorus.routines.add(
            employee="Moe", intent_template="weekly review", schedule="0 9 * * 1"
        )
        stored = ledger.routines.get(view.id)
        assert stored is not None
        assert stored.employee_id == "moe"
        assert stored.intent_template == "weekly review"
        # S1 default is coalesce (safe-by-default), not the legacy skip_if_active.
        assert stored.concurrency_policy is RoutineConcurrency.COALESCE
        assert stored.status is RoutineStatus.ACTIVE
        (trigger,) = view.triggers
        assert trigger.kind is TriggerKind.CRON
        assert trigger.cron_expression == "0 9 * * 1"
        assert trigger.next_run_at is not None  # parse_cron computed the first edge
    finally:
        ledger.close()


def test_add_routine_resolves_a_name_to_its_slug() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Big Moe", role="manager")
        view = chorus.routines.add(
            employee="Big Moe", intent_template="x", schedule="0 * * * *"
        )
        assert view.employee_id == "big-moe"
    finally:
        ledger.close()


def test_add_routine_for_an_unknown_employee_is_fail_closed() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        with pytest.raises(UnknownEmployee):
            _chorus(ledger).routines.add(
                employee="ghost", intent_template="x", schedule="0 * * * *"
            )
        # nothing persisted on the failed path
        assert ledger.routines.list_active() == []
    finally:
        ledger.close()


def test_add_routine_honours_an_explicit_concurrency_enum() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Moe", role="manager")
        view = chorus.routines.add(
            employee="Moe",
            intent_template="x",
            schedule="0 * * * *",
            concurrency=RoutineConcurrency.ALWAYS,
        )
        assert view.concurrency_policy is RoutineConcurrency.ALWAYS
    finally:
        ledger.close()


def test_list_routines_filters_by_employee() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Moe", role="manager")
        chorus.hire(name="Ada", role="engineer", reports_to="moe")
        chorus.routines.add(employee="Moe", intent_template="m", schedule="0 * * * *")
        chorus.routines.add(employee="Ada", intent_template="a", schedule="0 * * * *")
        assert {v.employee_id for v in chorus.routines.list()} == {"moe", "ada"}
        assert [v.employee_id for v in chorus.routines.list(employee="Ada")] == ["ada"]
    finally:
        ledger.close()


def test_routine_view_carries_triggers_and_recent_runs() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Moe", role="manager")
        view = chorus.routines.add(employee="Moe", intent_template="x", schedule="0 * * * *")
        shown = chorus.routines.get(view.id)
        assert len(shown.triggers) == 1
        assert shown.recent_runs == ()  # nothing has fired yet
    finally:
        ledger.close()


def test_pause_then_resume_toggles_the_firing_status() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger)
        chorus.hire(name="Moe", role="manager")
        view = chorus.routines.add(employee="Moe", intent_template="x", schedule="0 * * * *")

        chorus.routines.pause(view.id)
        assert chorus.routines.get(view.id).status is RoutineStatus.PAUSED
        assert ledger.routines.list_active() == []  # paused routines drop out of the firing set

        chorus.routines.resume(view.id)
        assert chorus.routines.get(view.id).status is RoutineStatus.ACTIVE
        assert [r.id for r in ledger.routines.list_active()] == [view.id]
    finally:
        ledger.close()
