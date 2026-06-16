"""The console's value types — the loop signal and the session's default clock."""

from __future__ import annotations

from datetime import UTC

import pytest

from chorus.ledger import SqliteLedger
from chorus_cli import CliSession, LoopSignal
from chorus_cli._context import utc_now

pytestmark = pytest.mark.unit


def test_loop_signal_is_a_named_enum() -> None:
    assert LoopSignal.QUIT is not LoopSignal.CONTINUE
    assert LoopSignal.QUIT.value == "quit"


def test_utc_now_is_timezone_aware() -> None:
    assert utc_now().tzinfo is UTC


def test_session_defaults_to_the_utc_clock(ledger: SqliteLedger) -> None:
    assert CliSession(ledger=ledger).clock is utc_now
