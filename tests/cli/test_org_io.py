"""The console's ``export`` / ``import`` verbs — org as data, end to end (spec 09 §3).

Seed an org via ``hire``, ``export`` it to a git-markdown tree, then ``import`` that tree into a
*fresh* ledger and prove the org (employees + ``reports_to`` edges) re-materialized — the round-trip
that makes GitWorkforce the portable serialization of the live ledger store.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from chorus.ledger import SqliteLedger
from chorus_cli import CliSession, Console, LoopSignal, dispatch
from chorus_cli._commands import REGISTRY

pytestmark = pytest.mark.integration


def _run(line: str, session: CliSession) -> tuple[LoopSignal, str]:
    buffer = io.StringIO()
    signal = dispatch(line, session=session, console=Console(out=buffer, colour=False), registry=REGISTRY)
    return signal, buffer.getvalue()


def test_export_writes_the_tree_and_reports_the_count(
    session: CliSession, tmp_path: Path
) -> None:
    _run("hire boss Boss manager", session)
    _run("hire alice Alice engineer boss", session)
    org = str(tmp_path / "org")

    _, out = _run(f"export {org}", session)

    assert "exported 2 employees" in out
    assert (tmp_path / "org" / "employees" / "alice" / "role.md").exists()


def test_export_then_import_round_trips_into_a_fresh_ledger(
    session: CliSession, tmp_path: Path
) -> None:
    _run("hire boss Boss manager", session)
    _run("hire alice Alice engineer boss", session)
    org = str(tmp_path / "org")
    _run(f"export {org}", session)

    fresh_ledger = SqliteLedger.open(":memory:")
    try:
        fresh = CliSession(ledger=fresh_ledger)
        _, out = _run(f"import {org}", fresh)
        assert "imported 2 employees" in out
        alice = fresh_ledger.employees.get("alice")
        assert alice is not None  # a real, assignable ledger row
        assert alice.reports_to == "boss"  # the org edge survived
    finally:
        fresh_ledger.close()


def test_import_into_a_populated_ledger_reports_the_conflict(
    session: CliSession, tmp_path: Path
) -> None:
    _run("hire boss Boss manager", session)
    org = str(tmp_path / "org")
    _run(f"export {org}", session)

    # Importing the same org back over itself collides on the existing slug — reported, not crashed.
    _, out = _run(f"import {org}", session)
    assert "import failed" in out


def test_export_wrong_arity_reports_usage(session: CliSession) -> None:
    _, out = _run("export", session)
    assert "usage: export <dir>" in out
