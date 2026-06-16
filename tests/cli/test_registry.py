"""The command registry: decorator registration, lookup, aliases, duplicate guard."""

from __future__ import annotations

import pytest

from chorus_cli import CommandContext, CommandRegistry, LoopSignal
from chorus_cli._registry import DuplicateCommandError

pytestmark = pytest.mark.unit


def _noop(ctx: CommandContext) -> LoopSignal:
    return LoopSignal.CONTINUE


def test_command_decorator_registers_and_returns_handler() -> None:
    registry = CommandRegistry()

    @registry.command("ping", summary="say pong", usage="ping")
    def handler(ctx: CommandContext) -> LoopSignal:
        return LoopSignal.CONTINUE

    assert handler is registry.get("ping").handler  # decorator returns the function unchanged
    command = registry.get("ping")
    assert command is not None
    assert command.name == "ping"
    assert command.summary == "say pong"
    assert command.usage == "ping"


def test_get_unknown_returns_none() -> None:
    assert CommandRegistry().get("nope") is None


def test_duplicate_registration_is_rejected() -> None:
    registry = CommandRegistry()
    registry.command("ping", summary="a", usage="ping")(_noop)
    with pytest.raises(DuplicateCommandError):
        registry.command("ping", summary="b", usage="ping")(_noop)


def test_alias_points_a_second_verb_at_one_command() -> None:
    registry = CommandRegistry()
    registry.command("quit", summary="leave", usage="quit")(_noop)
    registry.alias("exit", of="quit")

    assert registry.get("exit") is registry.get("quit")


def test_alias_to_unknown_command_raises() -> None:
    with pytest.raises(KeyError):
        CommandRegistry().alias("exit", of="quit")


def test_alias_over_an_existing_verb_is_rejected() -> None:
    registry = CommandRegistry()
    registry.command("quit", summary="leave", usage="quit")(_noop)
    registry.command("help", summary="h", usage="help")(_noop)
    with pytest.raises(DuplicateCommandError):
        registry.alias("help", of="quit")


def test_visible_folds_aliases_and_keeps_registration_order() -> None:
    registry = CommandRegistry()
    registry.command("help", summary="h", usage="help")(_noop)
    registry.command("quit", summary="q", usage="quit")(_noop)
    registry.alias("exit", of="quit")

    assert [c.name for c in registry.visible()] == ["help", "quit"]
