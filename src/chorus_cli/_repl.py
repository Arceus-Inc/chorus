"""The read-eval loop and its one-line dispatch.

``run_repl`` is the interactive console: read a line, dispatch it to a command, repeat until a
handler returns :data:`LoopSignal.QUIT` or the input ends (EOF / Ctrl-C). Both the input source and
the output stream are injected, so a test drives the whole loop with a scripted input function and an
``io.StringIO`` — no real stdin, no TTY.
"""

from __future__ import annotations

import shlex
import sys
from collections.abc import Callable
from typing import TextIO

from chorus_cli._context import CliSession, CommandContext, LoopSignal
from chorus_cli._registry import CommandRegistry
from chorus_cli._render import Console

_PROMPT = "chorus> "


def dispatch(
    line: str, *, session: CliSession, console: Console, registry: CommandRegistry
) -> LoopSignal:
    """Parse one input line into a verb + args and run its command.

    A blank line is a no-op ``CONTINUE``; an unknown verb is reported, not fatal; a malformed line
    (unbalanced quotes) is reported rather than crashing the loop. The verb is matched exactly — no
    fuzzy or prefix matching, so dispatch is unambiguous.
    """
    try:
        tokens = _split_line(line)
    except ValueError as exc:
        console.error(f"could not parse line: {exc}")
        return LoopSignal.CONTINUE
    if not tokens:
        return LoopSignal.CONTINUE

    verb, *args = tokens
    command = registry.get(verb)
    if command is None:
        console.error(f"unknown command: {verb!r} (try 'help')")
        return LoopSignal.CONTINUE
    try:
        return command.handler(CommandContext(args=tuple(args), session=session, out=console))
    except Exception as exc:  # a failing command must never crash the console (cf. dream's repl)
        console.error(f"{type(exc).__name__}: {exc}")
        return LoopSignal.CONTINUE


def _split_line(line: str) -> list[str]:
    """Split a console line without treating Windows path separators as escapes."""
    if sys.platform != "win32":
        return shlex.split(line)
    lexer = shlex.shlex(line, posix=False)
    lexer.whitespace_split = True
    return [_strip_outer_quotes(token) for token in lexer]


def _strip_outer_quotes(token: str) -> str:
    if len(token) >= 2 and token[0] == token[-1] and token[0] in {'"', "'"}:
        return token[1:-1]
    return token


def run_repl(
    session: CliSession,
    registry: CommandRegistry,
    *,
    input_func: Callable[[str], str] = input,
    output: TextIO | None = None,
    colour: bool | None = None,
) -> int:
    """Drive the console until quit or end-of-input; return a process exit code.

    ``input_func`` is called once per line (raise ``EOFError`` / ``KeyboardInterrupt`` to leave);
    ``output`` defaults to stdout. ``colour`` defaults to auto (on only for a real terminal).
    """
    stream = output if output is not None else sys.stdout
    use_colour = stream.isatty() if colour is None else colour
    console = Console(out=stream, colour=use_colour)

    if session.minimal_mode:
        console.line(
            "chorus demo -- employee heartbeat is live. commands: assign-task, check, help, quit"
        )
        # Reuse the command bootstrap path so startup and steady-state stay identical.
        dispatch("help", session=session, console=console, registry=registry)
    else:
        console.line("chorus console -- type 'help' for commands, 'quit' to exit")
    while True:
        try:
            line = input_func(_PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.line()
            return 0
        if dispatch(line, session=session, console=console, registry=registry) is LoopSignal.QUIT:
            return 0


__all__ = ["dispatch", "run_repl"]
