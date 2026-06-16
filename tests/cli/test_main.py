"""The ``chorus`` entrypoint: arg parsing and an end-to-end run over a throwaway ledger."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from chorus.ledger import SqliteLedger
from chorus_cli import main
from chorus_cli.__main__ import _beat_service_from_env, build_parser

pytestmark = pytest.mark.integration

MakeInput = Callable[[list[str]], Callable[[str], str]]


@pytest.fixture(autouse=True)
def _no_azure_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``main`` hermetic — never build a real beat service from the developer's environment."""
    for var in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_BASE_URL", "AZURE_OPENAI_DEPLOYMENT"):
        monkeypatch.delenv(var, raising=False)


def test_parser_defaults_to_the_default_db() -> None:
    args = build_parser().parse_args([])
    assert args.db == "chorus.db"


def test_parser_accepts_a_db_path() -> None:
    args = build_parser().parse_args(["--db", ":memory:"])
    assert args.db == ":memory:"


def test_main_runs_a_session_and_returns_zero(make_input: MakeInput) -> None:
    out = io.StringIO()
    code = main(
        ["--db", ":memory:"],
        input_func=make_input(["hire alice Alice engineer", "employee alice", "quit"]),
        output=out,
    )
    assert code == 0
    assert "hired alice" in out.getvalue()
    assert "engineer" in out.getvalue()


def test_main_exits_cleanly_on_eof(make_input: MakeInput) -> None:
    out = io.StringIO()
    assert main(["--db", ":memory:"], input_func=make_input([]), output=out) == 0


def test_beat_service_is_none_without_credentials() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        assert _beat_service_from_env(ledger) is None  # env cleared by the autouse fixture
    finally:
        ledger.close()


def test_beat_service_is_built_when_credentials_are_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "k")
    monkeypatch.setenv("AZURE_OPENAI_BASE_URL", "https://example/openai/v1")
    monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-x")
    sentinel = object()
    monkeypatch.setattr("chorus_cli._beats.build_beat_service", lambda *a, **k: sentinel)

    ledger = SqliteLedger.open(":memory:")
    try:
        assert _beat_service_from_env(ledger) is sentinel
    finally:
        ledger.close()
