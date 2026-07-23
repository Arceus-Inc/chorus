"""Safe FTS5 MATCH expressions — Hermes-style sanitize, implicit AND (not OR soup)."""

from __future__ import annotations

import re

MAX_FTS5_QUERY_CHARS = 2_048

_FTS_SPECIAL = re.compile(r'[+{}():"^]')
_REPEAT_STAR = re.compile(r"\*+")
_LEADING_STAR = re.compile(r"(^|\s)\*")
_LEADING_BOOL = re.compile(r"(?i)^(AND|OR|NOT)\b\s*")
_TRAILING_BOOL = re.compile(r"(?i)\s+(AND|OR|NOT)\s*$")
_COMPOUND_TOKEN = re.compile(r"\b(\w+(?:[._-]\w+)+)\b")


def sanitize_fts5_query(query: str) -> str:
    """Turn free text into a safe FTS5 ``MATCH`` expression.

    Multi-word queries keep spaces (FTS5 implicit AND). Hyphenated / dotted
    tokens are quoted as phrases. Balanced ``\"…\"`` phrases are preserved.
    Never OR-joins every token — that was the prior chorus widening bug.
    """
    if not query or not query.strip():
        return ""
    query = query[:MAX_FTS5_QUERY_CHARS]

    quoted_parts: list[str] = []
    pieces: list[str] = []
    i = 0
    while i < len(query):
        ch = query[i]
        if ch != '"':
            pieces.append(ch)
            i += 1
            continue
        end = query.find('"', i + 1)
        if end == -1:
            pieces.append(" ")
            i += 1
            continue
        quoted_parts.append(query[i : end + 1])
        pieces.append(f"\x00Q{len(quoted_parts) - 1}\x00")
        i = end + 1

    sanitized = "".join(pieces)
    sanitized = _FTS_SPECIAL.sub(" ", sanitized)
    sanitized = _REPEAT_STAR.sub("*", sanitized)
    sanitized = _LEADING_STAR.sub(r"\1", sanitized)
    sanitized = _LEADING_BOOL.sub("", sanitized.strip())
    sanitized = _TRAILING_BOOL.sub("", sanitized.strip())
    sanitized = _COMPOUND_TOKEN.sub(r'"\1"', sanitized)

    for index, quoted in enumerate(quoted_parts):
        sanitized = sanitized.replace(f"\x00Q{index}\x00", quoted)

    return " ".join(sanitized.split())


__all__ = ["MAX_FTS5_QUERY_CHARS", "sanitize_fts5_query"]
