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
from typing import Protocol, runtime_checkable

from chorus.heartbeat import TickReport
from chorus.ledger import SqliteLedger
from chorus_cli._render import Console


@runtime_checkable
class BeatService(Protocol):
    """The console's seam to the running kernel — pulse it once and report what happened.

    A :class:`~chorus.heartbeat.Scheduler` wired with a real dream beat runner sits behind this; the
    console only needs to ask it to tick. Kept as a Protocol so the dream/scheduler wiring stays at
    the composition root and the command handlers (and their tests) depend only on this shape.
    """

    def run_tick(self) -> TickReport:
        """Run one kernel pulse (recover → cron → monitors → dispatch) and await its beats."""
        ...

    @property
    def model(self) -> str:
        """The model/deployment the beats run against — shown when the console reports a tick."""
        ...


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
    """The console's live state: the open ledger, the clock, and an optional beat service.

    One session is built at startup and handed to every command unchanged; the ledger it holds is
    the single durable backend the whole console reads and writes. ``beats`` is wired only when the
    kernel can run a real beat (Azure keys present) — otherwise it stays ``None`` and ``tick`` says so.
    """

    ledger: SqliteLedger
    clock: Callable[[], datetime] = utc_now
    beats: BeatService | None = None
    db_path: str | None = None
    company_id: str = "company"  # the scope id for company-wide budgets (spec 04 §3)
    # Minimal operator UX: show only assign-task/check/quit/help in the help table.
    minimal_mode: bool = False
    # The line source the interactive console reads from. Defaults to real stdin; a test injects a
    # scripted reader. Held on the session (not just passed to ``run_repl``) so a modal sub-loop such
    # as ``chat`` can keep reading from the same source after a command hands off to it.
    input_func: Callable[[str], str] = input


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
