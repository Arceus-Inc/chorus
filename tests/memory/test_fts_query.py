"""FTS5 MATCH builder — Hermes-style sanitize + implicit AND (not OR-joined quoted soup)."""

from __future__ import annotations

import pytest

from chorus.memory.episodic.fts_query import sanitize_fts5_query

pytestmark = pytest.mark.unit


def test_empty_and_whitespace_yield_empty() -> None:
    assert sanitize_fts5_query("") == ""
    assert sanitize_fts5_query("   ") == ""


def test_multi_word_is_implicit_and_not_or() -> None:
    """Spaces stay spaces — FTS5 treats them as AND; never '\"a\" OR \"b\"'."""
    got = sanitize_fts5_query("retry upload timeout")
    assert " OR " not in got
    assert got == "retry upload timeout"


def test_preserves_quoted_phrase() -> None:
    assert sanitize_fts5_query('"exact phrase" retry') == '"exact phrase" retry'


def test_hyphenated_and_dotted_terms_are_quoted_as_phrases() -> None:
    got = sanitize_fts5_query("fix chat-send and P2.2")
    assert '"chat-send"' in got
    assert '"P2.2"' in got


def test_strips_fts_special_chars_that_break_match() -> None:
    got = sanitize_fts5_query("TODO: fix (retry) +pool")
    assert ":" not in got
    assert "(" not in got
    assert ")" not in got
    assert "+" not in got
    assert "TODO" in got
    assert "fix" in got
    assert "retry" in got
    assert "pool" in got


def test_caps_overlong_input() -> None:
    long = "x" * 3000
    assert len(sanitize_fts5_query(long)) <= 2048


def test_unmatched_quote_does_not_raise() -> None:
    assert sanitize_fts5_query('retry "open') == "retry open"
