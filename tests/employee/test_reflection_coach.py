"""The managed, proposal-only Reflection Coach routine."""

from __future__ import annotations

from dataclasses import replace
from typing import cast

import pytest

from chorus.cron._fire import fire_routine
from chorus.errors import RolePluginInvalid, UnknownEmployee
from chorus.ledger import RoutineStatus
from chorus.roles import Isolation, PermissionMode, RoleRegistry, SandboxTier, default_roles
from chorus.testing import open_test_ledger
from chorus.workforce import LedgerWorkforce
from chorus_employee.reflection_coach import (
    REFLECTION_COACH_ROUTINE,
    RecentAgentReflectionPolicy,
    ReflectionCoachConfiguration,
    install_reflection_coach,
    reflection_coach_plugin,
)

pytestmark = pytest.mark.integration


def test_reflection_coach_has_an_isolated_proposal_only_harness() -> None:
    manifest = reflection_coach_plugin().manifest

    assert manifest.isolation is Isolation.WORKTREE
    assert manifest.sandbox is SandboxTier.READ_ONLY
    assert manifest.permission_mode is PermissionMode.PLAN
    assert "write_file" not in manifest.tools
    assert "git" not in manifest.tools
    assert "comment" in manifest.disallowed_tools
    assert "reflection_coach" in {plugin.name for plugin in default_roles()}


def test_managed_configuration_cannot_allow_the_coach_to_target_itself() -> None:
    with pytest.raises(ValueError, match="exclude its own employee"):
        ReflectionCoachConfiguration(
            employee_id="reflection-coach",
            targeting_policy=RecentAgentReflectionPolicy(("someone-else",)),
        )


def test_declared_initial_status_is_validated_before_installation() -> None:
    plugin = reflection_coach_plugin()
    invalid_routine = replace(
        REFLECTION_COACH_ROUTINE,
        initial_status=cast(RoutineStatus, "not-a-status"),
    )
    invalid_plugin = replace(plugin, declared_routines=(invalid_routine,))

    with pytest.raises(RolePluginInvalid, match="invalid initial_status"):
        RoleRegistry().register(invalid_plugin)


def test_managed_coach_install_is_idempotent_and_paused_until_resumed() -> None:
    ledger = open_test_ledger()
    try:
        workforce = LedgerWorkforce(ledger.employees)
        roles = RoleRegistry()

        first = install_reflection_coach(ledger=ledger, workforce=workforce, roles=roles)
        second = install_reflection_coach(ledger=ledger, workforce=workforce, roles=roles)

        assert first.reconciliation.created == (REFLECTION_COACH_ROUTINE.routine_key,)
        assert second.reconciliation.unchanged == (REFLECTION_COACH_ROUTINE.routine_key,)
        assert second.employee == first.employee
        assert first.targeting_policy.allows(first.employee.id) is False
        assert first.targeting_policy.allows("another-agent") is True
        assert roles.get("reflection_coach") == reflection_coach_plugin()

        routine = ledger.routines.by_key(first.employee.id, REFLECTION_COACH_ROUTINE.routine_key)
        assert routine is not None
        assert routine.status is RoutineStatus.PAUSED
        assert "evidence clustering" in routine.intent_template.lower()
        assert "minimal reviewable diffs" in routine.intent_template.lower()
        assert "representative-success replay" in routine.intent_template.lower()
        assert "proposal-only" in routine.intent_template.lower()

        (trigger,) = ledger.routine_triggers.by_routine(routine.id)
        assert trigger.next_run_at is not None
        assert fire_routine(ledger, trigger, now=trigger.next_run_at) is None
        assert ledger.routine_runs.by_routine(routine.id) == []

        ledger.routines.set_status(routine.id, RoutineStatus.ACTIVE)
        assert fire_routine(ledger, trigger, now=trigger.next_run_at) is not None
    finally:
        ledger.close()


def test_failed_install_rolls_back_employee_and_routine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger = open_test_ledger()
    try:
        workforce = LedgerWorkforce(ledger.employees)
        roles = RoleRegistry()

        def fail_trigger_create(trigger: object) -> None:
            del trigger
            raise RuntimeError("trigger storage unavailable")

        monkeypatch.setattr(ledger.routine_triggers, "create", fail_trigger_create)
        with pytest.raises(RuntimeError, match="trigger storage unavailable"):
            install_reflection_coach(ledger=ledger, workforce=workforce, roles=roles)

        with pytest.raises(UnknownEmployee, match="no employee 'reflection-coach'"):
            workforce.get("reflection-coach")
        assert ledger.routines.list() == []
    finally:
        ledger.close()
