"""Hermes-style tool-choice matrix — canonical text is in Dream ``core-beliefs.md``.

Standing orders inject this at session start. Kept here only if a caller wants
the string without parsing the markdown file.
"""

from __future__ import annotations

TOOL_CHOICE_MATRIX = (
    "TOOL CHOICE (cheapest surface that fits): use a direct tool for read/write/run/lint; "
    "load `skill(name=…)` for multi-step craft; `spawn_subagent` only for a named specialist / "
    "fresh judgment that returns a typed artifact you cannot honestly author alone; just implement "
    "mechanical multi-step yourself. Prefer tool > skill > spawn. Durable state across beats goes "
    "in TODO.md"
)

__all__ = ["TOOL_CHOICE_MATRIX"]
