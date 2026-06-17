"""The ``company`` console command — show or create the shared company workspace.

The company workspace (``.chorus/work/{company}/repo`` on branch ``main``) is where every employee's
worktree is cut from. ``tick`` / ``chat`` create it lazily on the first beat; this command makes it a
first-class, explicit step — and lets you seed it from a real repo up front.
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


def _session(company_id: str) -> CliSession:
    return CliSession(ledger=SqliteLedger.open(":memory:"), company_id=company_id)


def test_company_init_creates_the_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    signal, out = _run("company init", _session("acme"))
    # the same path tick/chat resolve: <cwd>/.chorus/work/{company}/repo on branch main
    repo = tmp_path / ".chorus" / "work" / "acme" / "repo"
    assert (repo / ".git").exists()
    assert "acme" in out
    assert signal is LoopSignal.CONTINUE


def test_company_init_is_idempotent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = _session("acme")
    _run("company init", session)
    signal, out = _run("company init", session)  # re-running is a no-op, never an error
    assert signal is LoopSignal.CONTINUE
    assert "error" not in out.lower()


def test_company_init_seeds_from_a_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    _run(f"company init {src}", _session("acme"))

    # the seeded code is committed on the company main, so employees branch off real code
    assert (tmp_path / ".chorus" / "work" / "acme" / "repo" / "calc.py").exists()


def test_company_init_falls_back_to_the_seed_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "calc.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CHORUS_COMPANY_SEED", str(src))

    _run("company init", _session("acme"))  # no explicit seed arg → uses the env

    assert (tmp_path / ".chorus" / "work" / "acme" / "repo" / "calc.py").exists()


def test_company_show_reports_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    session = _session("acme")
    _, before = _run("company", session)  # no args → show
    assert "acme" in before
    assert "no" in before.lower()  # not created yet

    _run("company init", session)
    _, after = _run("company", session)
    assert "yes" in after.lower()  # now exists
