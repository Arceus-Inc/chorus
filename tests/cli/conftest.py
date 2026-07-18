"""Fixtures for the CLI console tests.

A real in-memory ledger (migrations applied, no dream, no network), a :class:`CliSession` over it,
and a buffer-backed :class:`Console` so every command's output is captured as plain text. The
``scripted_input`` helper feeds the loop canned lines then raises ``EOFError`` — the same seam dream's
REPL tests use to drive an interactive loop without stdin.
"""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from chorus.ledger import Ledger
from chorus_cli import CliSession, Console


@pytest.fixture
def session(ledger: Ledger) -> CliSession:
    """A console session over the in-memory ledger."""
    return CliSession(ledger=ledger)


@pytest.fixture
def buffer() -> io.StringIO:
    """The captured output stream."""
    return io.StringIO()


@pytest.fixture
def console(buffer: io.StringIO) -> Console:
    """A plain (colour-off) console writing into the captured buffer."""
    return Console(out=buffer, colour=False)


def _scripted_input(lines: list[str]) -> Callable[[str], str]:
    """An ``input_func`` that yields ``lines`` in order, then raises ``EOFError``."""
    pending = iter(lines)

    def read(prompt: str = "") -> str:
        try:
            return next(pending)
        except StopIteration as exc:
            raise EOFError from exc

    return read


@pytest.fixture
def make_input() -> Callable[[list[str]], Callable[[str], str]]:
    """Factory fixture: ``make_input([...])`` builds a scripted ``input_func`` for the loop."""
    return _scripted_input
