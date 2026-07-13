"""Shared recall hit rendering — slim list hits and full run drill-down (R8)."""

from __future__ import annotations

from chorus.memory import (
    SprintDelta,
    beat_summary,
    is_deliverable_path,
    narrative,
    recorded_at,
)

_MAX_FILES_SHOWN = 8

_OUTCOME_HINT: dict[str, str] = {
    "done": "finished — reuse what worked",
    "needs_changes": "failed a check — avoid repeating that approach",
    "incomplete": "timed out mid-build — continue from files + TODO.md, do not restart",
    "blocked": "stranded — inspect root cause before continuing",
}


def outcome_hint(outcome: str) -> str:
    """One-line guidance for how to treat a past beat outcome."""
    return _OUTCOME_HINT.get(outcome, "use as past evidence")


def deliverable_files(delta: SprintDelta) -> list[str]:
    """Product / test paths only — drop harness noise even on pre-filter records."""
    return [path for path in delta.files_touched if is_deliverable_path(path)][:_MAX_FILES_SHOWN]


def slim_hit_dict(
    delta: SprintDelta,
    *,
    rank_note: str | None = None,
    snippet: str | None = None,
) -> dict[str, object]:
    """One recall list hit — summary / FTS snippet; full prose via ``get_run``."""
    hit: dict[str, object] = {
        "run_id": delta.run_id,
        "outcome": delta.outcome,
        "intent": delta.intent[:200],
        "summary": beat_summary(delta.body, intent=delta.intent),
        "files_touched": deliverable_files(delta),
        "recorded_at": recorded_at(delta).isoformat(),
        "hint": outcome_hint(delta.outcome),
        "drill_down": f"get_run(run_id={delta.run_id!r})",
    }
    if snippet:
        hit["snippet"] = snippet
    if rank_note:
        hit["rank_note"] = rank_note
    return hit


def format_slim_hit(hit: dict[str, object]) -> str:
    raw_files = hit["files_touched"]
    files = list(raw_files) if isinstance(raw_files, list) else []
    files_s = ", ".join(str(path) for path in files) if files else "(none)"
    # Query mode: FTS snippet is the match window; recency keeps first-sentence summary.
    teaser = str(hit.get("snippet") or hit.get("summary") or "").strip()
    teaser_key = "snippet" if hit.get("snippet") else "summary"
    teaser_line = f"\n  {teaser_key}: {teaser}" if teaser else ""
    rank_note = str(hit.get("rank_note") or "").strip()
    rank_line = f"\n  rank_note: {rank_note}" if rank_note else ""
    return (
        f"- [{hit['outcome']}] {str(hit['run_id'])[:12]}… — {hit['hint']}\n"
        f"  intent: {hit['intent']!r}\n"
        f"  files: {files_s}{teaser_line}{rank_line}\n"
        f"  drill_down: {hit['drill_down']}"
    )


def format_full_run(delta: SprintDelta) -> str:
    """Full episodic record for ``get_run``."""
    files = deliverable_files(delta)
    files_s = ", ".join(files) if files else "(none)"
    artifacts_s = ", ".join(delta.artifacts) if delta.artifacts else "(none)"
    prose = narrative(delta.body).strip()
    prose_block = f"\nprose:\n{prose}\n" if prose else ""
    return (
        f"run_id: {delta.run_id}\n"
        f"task_id: {delta.task_id}\n"
        f"outcome: {delta.outcome} — {outcome_hint(delta.outcome)}\n"
        f"intent: {delta.intent!r}\n"
        f"recorded_at: {recorded_at(delta).isoformat()}\n"
        f"files: {files_s}\n"
        f"artifacts: {artifacts_s}"
        f"{prose_block}"
    )


__all__ = [
    "deliverable_files",
    "format_full_run",
    "format_slim_hit",
    "outcome_hint",
    "slim_hit_dict",
]
