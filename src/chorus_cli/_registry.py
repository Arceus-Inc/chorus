"""``Command`` + ``CommandRegistry`` — the verb table the console dispatches through.

A command is a frozen record tying a verb to its help and its handler; the registry is an explicit,
ordered table populated by the ``@registry.command(...)`` decorator at import time. No reflection,
no ``getattr`` dispatch — every verb the console knows is registered by name in one place, and an
unknown verb is a first-class ``None`` lookup the loop reports.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from chorus_cli._context import CommandContext, LoopSignal

Handler = Callable[[CommandContext], LoopSignal]


@dataclass(frozen=True)
class Command:
    """One verb: its name, a one-line summary, a usage string, and the handler to run."""

    name: str
    summary: str
    usage: str
    handler: Handler


class DuplicateCommandError(ValueError):
    """Two commands registered under the same verb — a programming error, caught at import."""


class CommandRegistry:
    """An insertion-ordered table of :class:`Command`, keyed by verb."""

    def __init__(self) -> None:
        self._commands: dict[str, Command] = {}

    def command(
        self, name: str, *, summary: str, usage: str
    ) -> Callable[[Handler], Handler]:
        """Decorator: register ``handler`` under ``name``; returns it unchanged for normal use."""

        def register(handler: Handler) -> Handler:
            if name in self._commands:
                raise DuplicateCommandError(name)
            self._commands[name] = Command(
                name=name, summary=summary, usage=usage, handler=handler
            )
            return handler

        return register

    def alias(self, name: str, *, of: str) -> None:
        """Point a second verb at an already-registered command (e.g. ``?`` for ``help``)."""
        target = self._commands.get(of)
        if target is None:
            raise KeyError(of)
        if name in self._commands:
            raise DuplicateCommandError(name)
        self._commands[name] = target

    def get(self, name: str) -> Command | None:
        """The command for ``name``, or ``None`` if the verb is unknown."""
        return self._commands.get(name)

    def visible(self) -> tuple[Command, ...]:
        """The distinct commands in registration order — for the ``help`` listing (aliases folded)."""
        seen: set[str] = set()
        out: list[Command] = []
        for command in self._commands.values():
            if command.name in seen:
                continue
            seen.add(command.name)
            out.append(command)
        return tuple(out)


__all__ = [
    "Command",
    "CommandRegistry",
    "DuplicateCommandError",
    "Handler",
]
