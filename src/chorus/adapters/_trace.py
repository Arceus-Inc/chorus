"""Best-effort reader for dream's per-session subagent trace (spec 08 observability).

dream writes structured trace events to ``{working_dir}/.dream/sidecars/{session}/logs/trace.jsonl``.
The ``subagent.complete`` events carry counters (``turns_used``, ``tool_calls``, ``elapsed_seconds``)
that dream discards at its tool-dispatch boundary — ``dispatch`` returns ``(content, is_error)``, so
``ToolResult.metadata`` never reaches the ``on_event`` observer the chorus bridge listens on. This
reader recovers those counters post-run from the beat's sidecar trace.

Best-effort by construction: a missing dir, an unreadable file, or a malformed line yields no stats
rather than failing the beat. Observability must never be load-bearing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_SIDECARS = ".dream/sidecars"
_TRACE = "logs/trace.jsonl"


@dataclass(frozen=True)
class SubagentStat:
    """One ``subagent.complete`` trace record — dream's counters for a single spawn."""

    name: str
    success: bool
    turns_used: int
    tool_calls: int
    tool_errors: int
    elapsed_seconds: float


def sidecar_traces(working_dir: Path) -> frozenset[Path]:
    """Every sidecar ``trace.jsonl`` under ``working_dir`` (empty when the dir is absent)."""
    root = working_dir / _SIDECARS
    if not root.is_dir():
        return frozenset()
    return frozenset(root.glob(f"*/{_TRACE}"))


def newest_trace_since(working_dir: Path, seen: frozenset[Path]) -> Path | None:
    """The sidecar trace created *this beat* — the newest one not present in ``seen``.

    Each beat is a fresh dream session (a new sidecar dir), so diffing against the pre-run snapshot
    isolates this beat's trace without needing the session id (which dream never returns to chorus).
    """
    fresh = [p for p in sidecar_traces(working_dir) if p not in seen]
    if not fresh:
        return None
    return max(fresh, key=lambda p: p.stat().st_mtime)


def read_subagent_stats(trace: Path) -> tuple[SubagentStat, ...]:
    """Parse the ``subagent.complete`` records from a trace file (in spawn order)."""
    try:
        text = trace.read_text(encoding="utf-8")
    except OSError:
        return ()
    stats: list[SubagentStat] = []
    for line in text.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("event_type") != "subagent.complete":
            continue
        attrs = event.get("attributes") or {}
        stats.append(
            SubagentStat(
                name=str(attrs.get("subagent_name", "subagent")),
                success=bool(attrs.get("success", False)),
                turns_used=int(attrs.get("turns_used", 0)),
                tool_calls=int(attrs.get("tool_calls", 0)),
                tool_errors=int(attrs.get("tool_errors", 0)),
                elapsed_seconds=float(attrs.get("elapsed_seconds", 0.0)),
            )
        )
    return tuple(stats)


def beat_subagent_stats(working_dir: Path, seen: frozenset[Path]) -> tuple[SubagentStat, ...]:
    """Read this beat's subagent counters, or ``()`` when there is no fresh trace (best-effort)."""
    trace = newest_trace_since(working_dir, seen)
    return read_subagent_stats(trace) if trace is not None else ()


__all__ = [
    "SubagentStat",
    "beat_subagent_stats",
    "newest_trace_since",
    "read_subagent_stats",
    "sidecar_traces",
]
