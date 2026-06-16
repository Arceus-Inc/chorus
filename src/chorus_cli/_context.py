"""The console's value types — the loop signal, the session, and a command's context.

These are the small, immutable primitives every command handler is handed. Keeping them in one
module (no behaviour, just shape) lets the registry, the renderer, and the handlers all depend on
them without a cycle. The console is push-only over the ledger: a handler reads ``ctx.args``, calls
the real ledger/lifecycle layer through ``ctx.session.ledger``, and writes to ``ctx.out``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from chorus.ledger import SqliteLedger
from chorus_cli._render import Console


class LoopSignal(StrEnum):
    """A handler's answer to the loop: keep reading, or leave.

    An enum, not a bare ``bool`` — the call site reads ``signal is LoopSignal.QUIT`` instead of an
    opaque ``not handler(...)``, so the control flow is named at the point it matters.
    """

    CONTINUE = "continue"
    QUIT = "quit"


def utc_now() -> datetime:
    """The console's wall clock — injected so command stamping is deterministic under test."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class CliSession:
    """The console's live state: the open ledger and the clock it stamps writes with.

    One session is built at startup and handed to every command unchanged; the ledger it holds is
    the single durable backend the whole console reads and writes.
    """

    ledger: SqliteLedger
    clock: Callable[[], datetime] = utc_now


@dataclass(frozen=True)
class CommandContext:
    """Everything a command handler needs, assembled once per dispatched line.

    ``args`` is the already-tokenised tail of the line (the verb removed); ``session`` is the shared
    state; ``out`` is the render device the handler writes results and errors to.
    """

    args: tuple[str, ...]
    session: CliSession
    out: Console


__all__ = [
    "CliSession",
    "CommandContext",
    "LoopSignal",
    "utc_now",
]
