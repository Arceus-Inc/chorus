"""The ``chorus`` entrypoint: arg parsing and an end-to-end run over a throwaway ledger."""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path

import pytest

from chorus.ledger import SqliteLedger
from chorus_cli import main
from chorus_cli.__main__ import _beat_service_from_env, build_parser
from chorus_cli._beats import default_pricing_from_env

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


def test_parser_defaults_to_dotenv() -> None:
    assert build_parser().parse_args([]).env_file == ".env"


def test_main_loads_dotenv_and_wires_the_beat_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, make_input: MakeInput
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "AZURE_OPENAI_API_KEY=k\n"
        "AZURE_OPENAI_BASE_URL=https://x/openai/v1\n"
        "AZURE_OPENAI_DEPLOYMENT=gpt-x\n",
        encoding="utf-8",
    )
    sentinel = object()
    monkeypatch.setattr("chorus_cli._beats.build_beat_service", lambda *a, **k: sentinel)
    captured: dict[str, object] = {}

    def fake_run_repl(session: object, registry: object, **kwargs: object) -> int:
        captured["beats"] = session.beats  # type: ignore[attr-defined]
        return 0

    monkeypatch.setattr("chorus_cli.__main__.run_repl", fake_run_repl)

    code = main(["--db", ":memory:", "--env-file", str(env_file)], input_func=make_input([]))
    assert code == 0
    assert captured["beats"] is sentinel


def test_main_runs_a_session_and_returns_zero(make_input: MakeInput) -> None:
    out = io.StringIO()
    code = main(
        ["--db", ":memory:"],
        input_func=make_input(["hire Alice engineer", "employee alice", "quit"]),
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
        assert _beat_service_from_env(ledger, company_id="acme") is None  # env cleared by fixture
    finally:
        ledger.close()


def test_pricing_defaults_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHORUS_PRICE_INPUT_CENTS_PER_MTOK", raising=False)
    monkeypatch.delenv("CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK", raising=False)
    rate = default_pricing_from_env().rate_for("any-model")
    assert (
        rate is not None and rate.input_cents_per_mtok == 125 and rate.output_cents_per_mtok == 1000
    )


def test_pricing_reads_env_and_ignores_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHORUS_PRICE_INPUT_CENTS_PER_MTOK", "200")
    monkeypatch.setenv("CHORUS_PRICE_OUTPUT_CENTS_PER_MTOK", "not-a-number")
    rate = default_pricing_from_env().rate_for("any-model")
    assert rate is not None and rate.input_cents_per_mtok == 200
    assert rate.output_cents_per_mtok == 1000  # malformed -> default


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
        assert _beat_service_from_env(ledger, company_id="acme") is sentinel
    finally:
        ledger.close()
