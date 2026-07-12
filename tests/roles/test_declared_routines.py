"""Plugin-declared routines: the declaration + registry validation (spec 13 §5.1, M4 S6).

A role plugin carries its own standing schedule as ``declared_routines`` — a tuple of
:class:`RoutineDeclaration`. Registration is fail-closed: a declaration with a bad cron or an inline
secret in ``env`` is rejected (``RolePluginInvalid``) before the plugin can ever schedule anything.
"""

from __future__ import annotations

import pytest

from chorus.errors import RolePluginInvalid
from chorus.ledger import RoutineConcurrency, RoutineTarget
from chorus.outcomes import Verifier
from chorus.roles import (
    MemoryScope,
    RoleManifest,
    RolePlugin,
    RoleRegistry,
    RoutineDeclaration,
)

pytestmark = pytest.mark.unit


def _plugin(*, declarations: tuple[RoutineDeclaration, ...] = ()) -> RolePlugin:
    return RolePlugin(
        name="widget",
        manifest=RoleManifest(
            system_prompt="x", tools=("read_file",), memory_scope=MemoryScope.PROJECT
        ),
        dod_generator=lambda intent: Verifier.command("pytest -q"),
        outcome_kind="pr",
        declared_routines=declarations,
    )


def test_declaration_has_sensible_defaults() -> None:
    decl = RoutineDeclaration(
        routine_key="weekly", intent_template="do the weekly thing", schedule="0 9 * * 1"
    )
    assert decl.target is RoutineTarget.SPAWN_TASK
    assert decl.concurrency is RoutineConcurrency.COALESCE
    assert decl.env is None


def test_plugin_defaults_to_no_declarations() -> None:
    assert _plugin().declared_routines == ()


def test_a_valid_declaration_registers_cleanly() -> None:
    decl = RoutineDeclaration(routine_key="weekly", intent_template="plan", schedule="0 9 * * 1")
    reg = RoleRegistry.from_plugins([_plugin(declarations=(decl,))])
    assert reg.get("widget").declared_routines == (decl,)


def test_a_bad_cron_in_a_declaration_is_rejected_at_registration() -> None:
    bad = RoutineDeclaration(routine_key="weekly", intent_template="plan", schedule="not a cron")
    with pytest.raises(RolePluginInvalid, match="schedule"):
        RoleRegistry.from_plugins([_plugin(declarations=(bad,))])


def test_an_inline_secret_in_a_declaration_is_rejected_at_registration() -> None:
    leaky = RoutineDeclaration(
        routine_key="weekly",
        intent_template="plan",
        schedule="0 9 * * 1",
        env={"GITHUB_TOKEN": "ghp_rawvalue"},
    )
    with pytest.raises(RolePluginInvalid, match="secret"):
        RoleRegistry.from_plugins([_plugin(declarations=(leaky,))])


def test_a_ref_env_in_a_declaration_is_allowed() -> None:
    ok = RoutineDeclaration(
        routine_key="weekly",
        intent_template="plan",
        schedule="0 9 * * 1",
        env={"GITHUB_TOKEN": "ref:github_token"},
    )
    reg = RoleRegistry.from_plugins([_plugin(declarations=(ok,))])
    assert reg.get("widget").declared_routines[0].env == {"GITHUB_TOKEN": "ref:github_token"}
