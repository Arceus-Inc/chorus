"""Minimal find/replace for skill_manage(patch) — exact then whitespace-normalized.

Hermes uses a longer fuzzy chain; we keep the high-signal strategies and return
clear miss errors for the harness recovery contract.
"""

from __future__ import annotations

import re


def find_and_replace(
    content: str,
    old_string: str,
    new_string: str,
    *,
    replace_all: bool = False,
) -> tuple[str, int, str | None]:
    """Return ``(new_content, count, error)``."""
    if not old_string:
        return content, 0, "old_string cannot be empty"
    if old_string == new_string:
        return content, 0, "old_string and new_string are identical"

    if old_string in content:
        count = content.count(old_string) if replace_all else 1
        if not replace_all and content.count(old_string) > 1:
            return content, 0, "old_string matched multiple times; pass replace_all=true or narrow it"
        if replace_all:
            return content.replace(old_string, new_string), count, None
        return content.replace(old_string, new_string, 1), 1, None

    # Whitespace-normalized fallback (Hermes strategy subset)
    norm_map = _build_norm_map(content)
    norm_old = _normalize_ws(old_string)
    if not norm_old:
        return content, 0, "old_string not found"
    idxs = [i for i, (norm, _span) in enumerate(norm_map) if norm_old in norm]
    # Search in full normalized content
    full_norm = _normalize_ws(content)
    if norm_old not in full_norm:
        return content, 0, "old_string not found (tried exact + whitespace-normalized)"

    # Reconstruct via regex on original using flexible whitespace
    pattern = _ws_flexible_pattern(old_string)
    matches = list(re.finditer(pattern, content))
    if not matches:
        return content, 0, "old_string not found (tried exact + whitespace-normalized)"
    if not replace_all and len(matches) > 1:
        return content, 0, "old_string matched multiple times; pass replace_all=true or narrow it"
    if replace_all:
        return re.sub(pattern, lambda _m: new_string, content), len(matches), None
    start, end = matches[0].span()
    return content[:start] + new_string + content[end:], 1, None


def _normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _build_norm_map(content: str) -> list[tuple[str, tuple[int, int]]]:
    return [(_normalize_ws(content), (0, len(content)))]


def _ws_flexible_pattern(old_string: str) -> re.Pattern[str]:
    parts = re.split(r"(\s+)", old_string)
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if part.isspace():
            out.append(r"\s+")
        else:
            out.append(re.escape(part))
    return re.compile("".join(out))


__all__ = ["find_and_replace"]
