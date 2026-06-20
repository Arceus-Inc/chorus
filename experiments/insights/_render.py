"""Tiny ANSI rendering helpers — tables, headers, and colour the terminal can opt out of.

No dependency on ``rich``; the insights platform stays importable anywhere chorus is. Colour is
disabled automatically when stdout is not a TTY or ``NO_COLOR`` is set (https://no-color.org).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Sequence

_ENABLED = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

_CODES = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "grey": "\033[90m",
}


def set_color(enabled: bool) -> None:
    """Force colour on/off (the CLI's ``--no-color`` flag routes here)."""
    global _ENABLED
    _ENABLED = enabled


def paint(text: str, *styles: str) -> str:
    """Wrap ``text`` in the given style codes, or return it unchanged when colour is off."""
    if not _ENABLED or not styles:
        return text
    prefix = "".join(_CODES[s] for s in styles if s in _CODES)
    return f"{prefix}{text}{_CODES['reset']}"


# Status → colour, so a glance at any table reads "green = good, red = stuck".
_STATUS_STYLE = {
    "done": ("green",),
    "passed": ("green",),
    "succeeded": ("green",),
    "in_progress": ("cyan",),
    "running": ("cyan",),
    "in_review": ("blue",),
    "todo": ("yellow",),
    "backlog": ("grey",),
    "queued": ("grey",),
    "pending": ("yellow",),
    "blocked": ("red", "bold"),
    "failed": ("red",),
    "rejected": ("red",),
    "cancelled": ("grey",),
    "timed_out": ("red",),
}


def status(value: str) -> str:
    """Colour a status/verdict token by its meaning."""
    return paint(value, *_STATUS_STYLE.get(value, ()))


def header(title: str, *, width: int = 78) -> str:
    """A bold banner line for a section."""
    bar = "─" * width
    return f"{paint(bar, 'grey')}\n{paint(title, 'bold')}\n{paint(bar, 'grey')}"


def kv(label: str, value: object) -> str:
    """A dim ``label: value`` line."""
    return f"  {paint(label + ':', 'dim')} {value}"


def truncate(text: str, limit: int) -> str:
    """Collapse whitespace and clip ``text`` to ``limit`` chars with an ellipsis."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def table(headers: Sequence[str], rows: Sequence[Sequence[str]], *, indent: str = "  ") -> str:
    """Render a left-aligned fixed-width table. Cells may contain ANSI codes (width ignores them)."""
    columns = list(zip(*([headers, *rows]), strict=False)) if rows else [(h,) for h in headers]
    widths = [max(_visible_len(str(cell)) for cell in column) for column in columns]

    def render_row(cells: Sequence[str], *, head: bool = False) -> str:
        padded = [_pad(str(cell), widths[i]) for i, cell in enumerate(cells)]
        line = "  ".join(padded).rstrip()
        return indent + (paint(line, "bold") if head else line)

    lines = [render_row(headers, head=True)]
    lines.append(indent + paint("  ".join("─" * w for w in widths), "grey"))
    lines.extend(render_row(row) for row in rows)
    return "\n".join(lines)


def bar(count: int, total: int, *, width: int = 24) -> str:
    """A unicode proportion bar — used for tool/event histograms."""
    filled = 0 if total <= 0 else round(width * count / total)
    return paint("█" * filled, "cyan") + paint("░" * (width - filled), "grey")


def _visible_len(text: str) -> int:
    """Length of ``text`` ignoring ANSI escape sequences."""
    out, i = 0, 0
    while i < len(text):
        if text[i] == "\033":
            while i < len(text) and text[i] != "m":
                i += 1
            i += 1
            continue
        out += 1
        i += 1
    return out


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _visible_len(text))


__all__ = [
    "bar",
    "header",
    "kv",
    "paint",
    "set_color",
    "status",
    "table",
    "truncate",
]
