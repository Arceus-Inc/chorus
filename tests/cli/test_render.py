"""The console renderer: lines, errors, key/value blocks, tables, and colour gating."""

from __future__ import annotations

import io

import pytest

from chorus.testing import uid
from chorus_cli import Console

pytestmark = pytest.mark.unit


def _console() -> tuple[Console, io.StringIO]:
    buffer = io.StringIO()
    return Console(out=buffer, colour=False), buffer


def test_line_writes_a_single_terminated_line() -> None:
    console, buffer = _console()
    console.line("hello")
    assert buffer.getvalue() == "hello\n"


def test_error_is_prefixed() -> None:
    console, buffer = _console()
    console.error("boom")
    assert buffer.getvalue() == "error: boom\n"


def test_kv_renders_right_aligned_keys() -> None:
    console, buffer = _console()
    console.kv({"id": uid("t1"), "status": "todo"})
    assert buffer.getvalue() == f"    id  {uid('t1')}\nstatus  todo\n"


def test_kv_with_no_pairs_writes_nothing() -> None:
    console, buffer = _console()
    console.kv({})
    assert buffer.getvalue() == ""


def test_table_aligns_columns_under_headers() -> None:
    console, buffer = _console()
    console.table(("id", "role"), [("alice", "engineer"), ("bo", "pm")])
    assert buffer.getvalue() == ("id     role\nalice  engineer\nbo     pm\n")


def test_empty_table_prints_a_placeholder() -> None:
    console, buffer = _console()
    console.table(("id",), [])
    assert buffer.getvalue() == "(none)\n"


def test_colour_off_emits_no_ansi() -> None:
    console, buffer = _console()
    console.error("x")
    console.table(("h",), [("v",)])
    assert "\x1b[" not in buffer.getvalue()


def test_colour_on_wraps_with_ansi() -> None:
    buffer = io.StringIO()
    Console(out=buffer, colour=True).error("x")
    assert "\x1b[" in buffer.getvalue()
