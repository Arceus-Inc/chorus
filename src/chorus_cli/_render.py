"""``Console`` — the console's output device.

A thin, fully-injectable wrapper over a text stream. Every command writes through it (never bare
``print``) so tests drive the loop with an ``io.StringIO`` and assert on the captured text. Colour
is TTY-gated and off by default, so test output is plain and stable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TextIO

# ANSI styling — applied only when ``Console.colour`` is on (a real terminal).
_RESET = "\x1b[0m"
_DIM = "\x1b[2m"
_BOLD = "\x1b[1m"
_RED = "\x1b[31m"


@dataclass(frozen=True)
class Console:
    """A text sink with a few structured helpers (key/value blocks, tables, errors)."""

    out: TextIO
    colour: bool = False

    def _paint(self, code: str, text: str) -> str:
        """Wrap ``text`` in an ANSI ``code`` when colour is on, else return it untouched."""
        if not self.colour or not code:
            return text
        return f"{code}{text}{_RESET}"

    def line(self, text: str = "") -> None:
        """Write one line."""
        self.out.write(text + "\n")

    def error(self, text: str) -> None:
        """Write one error line, marked so a human (and a test) can tell it apart."""
        self.line(self._paint(_RED, f"error: {text}"))

    def kv(self, pairs: Mapping[str, object]) -> None:
        """Render aligned ``key: value`` rows — the shape used to show one record."""
        if not pairs:
            return
        width = max(len(key) for key in pairs)
        for key, value in pairs.items():
            self.line(f"{self._paint(_DIM, f'{key:>{width}}')}  {value}")

    def table(self, headers: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
        """Render a column-aligned table; an empty body prints a single dim placeholder."""
        if not rows:
            self.line(self._paint(_DIM, "(none)"))
            return
        cells = [[str(cell) for cell in row] for row in rows]
        widths = [
            max(len(headers[col]), *(len(row[col]) for row in cells))
            for col in range(len(headers))
        ]
        header = "  ".join(self._paint(_BOLD, h.ljust(widths[i])) for i, h in enumerate(headers))
        self.line(header.rstrip())
        for row in cells:
            line = "  ".join(row[i].ljust(widths[i]) for i in range(len(headers)))
            self.line(line.rstrip())


__all__ = ["Console"]
