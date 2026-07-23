"""Pre-beat-end TODO flush — warn the agent when beat wall-clock budget is almost exhausted.

OpenClaw-style: at 90% elapsed (10% budget remaining) the kernel arms a nudge file under
``.harness/``; the next tool result surfaces it so the agent syncs ``TODO.md`` before timeout.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TODO_FLUSH_REMAINING_FRACTION = 0.10
"""Arm the nudge when this fraction of the beat budget remains (default 10%)."""

_RELATIVE_PATH = Path(".harness") / "todo-flush-nudge.json"


@dataclass(frozen=True)
class TodoFlushNudge:
    """An armed beat-budget warning the agent should act on before the beat ends."""

    timeout_s: float
    remaining_s: float
    armed_at: str


def nudge_path_in(working_dir: Path) -> Path:
    """On-disk location of the armed nudge under an employee worktree."""
    return working_dir / _RELATIVE_PATH


def format_todo_flush_banner(*, remaining_s: float) -> str:
    """Human-facing warning appended to the next tool result when a nudge is armed."""
    secs = max(0, int(remaining_s))
    return (
        f"⚠ BEAT BUDGET WARNING: ~{secs}s remaining (<10% budget). "
        "Sync TODO.md NOW via todo_write — checkpoint each completed step before this beat ends."
    )


def write_todo_flush_nudge(
    working_dir: Path,
    *,
    timeout_s: float,
    remaining_s: float,
    armed_at: datetime | None = None,
) -> None:
    """Arm the nudge file so the next tool call surfaces the budget warning."""
    when = armed_at or datetime.now(UTC)
    payload = TodoFlushNudge(
        timeout_s=timeout_s,
        remaining_s=remaining_s,
        armed_at=when.isoformat(),
    )
    path = nudge_path_in(working_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload.__dict__), encoding="utf-8")


def read_todo_flush_nudge(working_dir: Path) -> TodoFlushNudge | None:
    """Return the armed nudge, or ``None`` when no flush warning is pending."""
    path = nudge_path_in(working_dir)
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return TodoFlushNudge(
        timeout_s=float(data["timeout_s"]),
        remaining_s=float(data["remaining_s"]),
        armed_at=str(data["armed_at"]),
    )


def clear_todo_flush_nudge(working_dir: Path) -> None:
    """Drop a pending nudge (beat start/end or after the agent synced TODO.md)."""
    path = nudge_path_in(working_dir)
    if path.is_file():
        path.unlink()


__all__ = [
    "TODO_FLUSH_REMAINING_FRACTION",
    "TodoFlushNudge",
    "clear_todo_flush_nudge",
    "format_todo_flush_banner",
    "nudge_path_in",
    "read_todo_flush_nudge",
    "write_todo_flush_nudge",
]
