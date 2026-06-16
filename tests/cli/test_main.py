"""The ``chorus`` entrypoint: arg parsing and an end-to-end run over a throwaway ledger."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest

from chorus_cli import main
from chorus_cli.__main__ import build_parser

pytestmark = pytest.mark.integration

MakeInput = Callable[[list[str]], Callable[[str], str]]


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
