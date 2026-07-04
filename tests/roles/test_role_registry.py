"""RoleRegistry validation + idempotency + conflict (spec 06 §2, spec 09 §1)."""

from __future__ import annotations

import pytest

from chorus.errors import RolePluginConflict, RolePluginInvalid
from chorus.outcomes import Verifier
from chorus.roles import (
    MemoryScope,
    RoleManifest,
    RolePlugin,
    RoleRegistry,
    default_roles,
)

pytestmark = pytest.mark.unit


def _plugin(
    name: str = "engineer",
    *,
    tools: tuple[str, ...] = ("read_file",),
    outcome_kind: str = "pr",
    dod: object = None,
) -> RolePlugin:
    return RolePlugin(
        name=name,
        manifest=RoleManifest(system_prompt="x", tools=tools, memory_scope=MemoryScope.PROJECT),
        dod_generator=dod or (lambda intent: Verifier.command("pytest -q")),
        outcome_kind=outcome_kind,
    )


def test_default_roles_register_cleanly() -> None:
    reg = RoleRegistry.from_plugins(default_roles())
    assert set(reg.names()) == {
        "engineer",
        "reviewer",
        "manager",
        "pm",
        "analyst",
        "marketer",
        "designer",
        "frontend_engineer",
    }


def test_get_returns_the_plugin() -> None:
    reg = RoleRegistry.from_plugins([_plugin("engineer")])
    assert reg.get("engineer").name == "engineer"
    assert "engineer" in reg


def test_get_unknown_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        RoleRegistry().get("ghost")


def test_empty_slug_is_invalid() -> None:
    with pytest.raises(RolePluginInvalid):
        RoleRegistry().register(_plugin("  "))


def test_unknown_tool_is_invalid_when_tools_are_known() -> None:
    reg = RoleRegistry(known_tools=frozenset({"read_file", "write_file"}))
    with pytest.raises(RolePluginInvalid):
        reg.register(_plugin(tools=("read_file", "curl")))


def test_known_tools_pass() -> None:
    reg = RoleRegistry(known_tools=frozenset({"read_file", "write_file"}))
    reg.register(_plugin(tools=("read_file",)))  # no raise
    assert "engineer" in reg


def test_outcome_kind_without_a_lander_is_invalid() -> None:
    reg = RoleRegistry(known_outcome_kinds=frozenset({"pr", "doc"}))
    with pytest.raises(RolePluginInvalid):
        reg.register(_plugin(outcome_kind="finding"))


def test_empty_outcome_kind_is_invalid() -> None:
    with pytest.raises(RolePluginInvalid):
        RoleRegistry().register(_plugin(outcome_kind=""))


def test_dod_generator_not_returning_a_verifier_is_invalid() -> None:
    with pytest.raises(RolePluginInvalid):
        RoleRegistry().register(_plugin(dod=lambda intent: "not a verifier"))


def test_dod_generator_that_raises_is_invalid() -> None:
    def boom(intent: str) -> Verifier:
        raise ValueError("nope")

    with pytest.raises(RolePluginInvalid):
        RoleRegistry().register(_plugin(dod=boom))


def test_illegal_permission_mode_is_invalid() -> None:
    bad = RolePlugin(
        name="engineer",
        manifest=RoleManifest(system_prompt="x", permission_mode="bogus"),  # type: ignore[arg-type]
        dod_generator=lambda intent: Verifier.command("pytest -q"),
        outcome_kind="pr",
    )
    with pytest.raises(RolePluginInvalid):
        RoleRegistry().register(bad)


def test_idempotent_reregister_of_same_object_is_a_noop() -> None:
    reg = RoleRegistry()
    plugin = _plugin("engineer")
    reg.register(plugin)
    reg.register(plugin)  # identical definition (same dod_generator object) -> no raise
    assert reg.get("engineer") is plugin


def test_conflicting_reregister_without_replace_raises() -> None:
    reg = RoleRegistry()
    reg.register(_plugin("engineer", tools=("read_file",)))
    with pytest.raises(RolePluginConflict):
        reg.register(_plugin("engineer", tools=("read_file", "write_file")))


def test_conflicting_reregister_with_replace_succeeds() -> None:
    reg = RoleRegistry()
    reg.register(_plugin("engineer", tools=("read_file",)))
    replacement = _plugin("engineer", tools=("read_file", "write_file"))
    reg.register(replacement, replace=True)
    assert reg.get("engineer") is replacement


def test_frozen_role_can_be_replaced_with_a_new_version() -> None:
    reg = RoleRegistry()
    reg.register(_plugin("engineer", tools=("read_file",)))
    reg.mark_used("engineer")
    assert reg.is_frozen("engineer")
    reg.register(_plugin("engineer", tools=("read_file", "git")), replace=True)  # new version
    assert reg.get("engineer").manifest.tools == ("read_file", "git")


def test_frozen_role_identical_reregister_is_still_a_noop() -> None:
    reg = RoleRegistry()
    plugin = _plugin("engineer")
    reg.register(plugin)
    reg.mark_used("engineer")
    reg.register(plugin)  # identical -> no raise even though frozen
    assert reg.get("engineer") is plugin
