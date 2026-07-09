"""Shared recall hit rendering — slim list hits and full run drill-down (R8)."""

from __future__ import annotations

from chorus.memory._fingerprint import is_deliverable_path
from chorus.memory._models import SprintDelta
from chorus.memory._narrative import beat_summary, narrative
from chorus.memory._recall_rank import recorded_at

_MAX_FILES_SHOWN = 8

_OUTCOME_HINT: dict[str, str] = {
    "done": "finished — reuse what worked",
    "needs_changes": "failed a check — avoid repeating that approach",
    "incomplete": "timed out mid-build — continue from files + TODO.md, do not restart",
    "blocked": "stranded — inspect root cause before continuing",
}


def deliverable_files(delta: SprintDelta) -> list[str]:
    """Product / test paths only — drop harness noise even on pre-filter records."""
    return [path for path in delta.files_touched if is_deliverable_path(path)][:_MAX_FILES_SHOWN]


def slim_hit_dict(delta: SprintDelta) -> dict[str, object]:
    """One recall list hit — summary only; full prose via ``get_run``."""
    return {
        "run_id": delta.run_id,
        "outcome": delta.outcome,
        "intent": delta.intent[:200],
        "summary": beat_summary(delta.body, intent=delta.intent),
        "files_touched": deliverable_files(delta),
        "recorded_at": recorded_at(delta).isoformat(),
        "hint": _OUTCOME_HINT.get(delta.outcome, "use as past evidence"),
        "drill_down": f"get_run(run_id={delta.run_id!r})",
    }


def format_slim_hit(hit: dict[str, object]) -> str:
    raw_files = hit["files_touched"]
    files = list(raw_files) if isinstance(raw_files, list) else []
    files_s = ", ".join(str(path) for path in files) if files else "(none)"
    summary = str(hit.get("summary") or "").strip()
    summary_line = f"\n  summary: {summary}" if summary else ""
    return (
        f"- [{hit['outcome']}] {str(hit['run_id'])[:12]}… — {hit['hint']}\n"
        f"  intent: {hit['intent']!r}\n"
        f"  files: {files_s}{summary_line}\n"
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
        f"outcome: {delta.outcome} — {_OUTCOME_HINT.get(delta.outcome, 'past evidence')}\n"
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
    "slim_hit_dict",
]
