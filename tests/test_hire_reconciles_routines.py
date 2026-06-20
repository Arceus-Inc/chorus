"""Hire-time reconciliation of plugin-declared routines (spec 13 §5, M4 S6).

Hiring an employee of a role provisions that role's declared routines for them — the chorus analog of
Paperclip "a plugin becomes active for a scope". The acceptance bar is literal: a brand-new plugin
(defined here in the test, never under ``src/chorus``) schedules recurring work the moment an employee
of its role is hired, with **zero kernel change** — only the public reconciler runs.
"""

from __future__ import annotations

import pytest

from chorus.facade import Caps, Chorus
from chorus.ledger import SqliteLedger
from chorus.observability import LedgerInspector
from chorus.outcomes import Verifier
from chorus.roles import (
    MemoryScope,
    RoleManifest,
    RolePlugin,
    RoleRegistry,
    RoutineDeclaration,
    default_roles,
)
from chorus.workforce import LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: SqliteLedger, registry: RoleRegistry) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=None,  # type: ignore[arg-type]
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=registry,
        caps=Caps(),
    )


def test_hiring_a_pm_provisions_its_weekly_routine() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger, RoleRegistry.from_plugins(default_roles()))
        pm = chorus.hire(name="Ada", role="pm")

        routine = ledger.routines.by_key(pm.id, "pm-weekly-planning-review")
        assert routine is not None
        assert routine.latest_revision_no == 1
        (trigger,) = ledger.routine_triggers.by_routine(routine.id)
        assert trigger.next_run_at is not None  # due edge computed — the tick will fire it
    finally:
        ledger.close()


def test_hiring_a_role_without_declarations_provisions_nothing() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger, RoleRegistry.from_plugins(default_roles()))
        eng = chorus.hire(name="Eli", role="engineer")
        assert ledger.routines.list(employee_id=eng.id) == []
    finally:
        ledger.close()


def test_a_fresh_plugin_schedules_with_no_kernel_change() -> None:
    """The acceptance bar: a plugin defined entirely outside ``src/chorus`` schedules a routine on
    hire — proof that a new role brings its own recurring work without touching the engine."""
    widget = RolePlugin(
        name="widget",
        manifest=RoleManifest(system_prompt="make widgets", tools=("read_file",),
                              memory_scope=MemoryScope.PROJECT),
        dod_generator=lambda intent: Verifier.command("pytest -q"),
        outcome_kind="pr",
        declared_routines=(
            RoutineDeclaration(
                routine_key="widget-nightly-audit",
                intent_template="audit the widgets",
                schedule="0 2 * * *",
            ),
        ),
    )
    ledger = SqliteLedger.open(":memory:")
    try:
        chorus = _chorus(ledger, RoleRegistry.from_plugins([*default_roles(), widget]))
        wendy = chorus.hire(name="Wendy", role="widget")

        routine = ledger.routines.by_key(wendy.id, "widget-nightly-audit")
        assert routine is not None
        assert routine.intent_template == "audit the widgets"
        (trigger,) = ledger.routine_triggers.by_routine(routine.id)
        assert trigger.cron_expression == "0 2 * * *" and trigger.next_run_at is not None
    finally:
        ledger.close()
