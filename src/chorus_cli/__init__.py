"""The ``chorus`` CLI — an interactive console over the durable ledger (spec 10 §2).

The entrypoint is :func:`main`; the console itself (:func:`run_repl`) and its command
:data:`REGISTRY` are exported so callers and tests can drive it with an injected ledger, input
function, and output stream.
"""

from __future__ import annotations

from chorus_cli.__main__ import main
from chorus_cli._commands import REGISTRY
from chorus_cli._context import CliSession, CommandContext, LoopSignal
from chorus_cli._registry import Command, CommandRegistry
from chorus_cli._render import Console
from chorus_cli._repl import dispatch, run_repl

__all__ = [
    "REGISTRY",
    "CliSession",
    "Command",
    "CommandContext",
    "CommandRegistry",
    "Console",
    "LoopSignal",
    "dispatch",
    "main",
    "run_repl",
]
