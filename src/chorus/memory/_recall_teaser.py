"""Beat-start episodic teaser — cheap orientation push (R6)."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from chorus.memory._models import SprintDelta
from chorus.memory._recall_rank import recorded_at

RECENT_FAILURE_DAYS = 14
_FAILURE_OUTCOMES = frozenset({"needs_changes", "blocked", "incomplete"})

_OUTCOME_HINT: dict[str, str] = {
    "done": "finished — reuse what worked",
    "needs_changes": "failed a check — avoid repeating that approach",
    "incomplete": "timed out mid-build — continue from files + TODO.md",
    "blocked": "stranded — inspect root cause before continuing",
}


def build_episodic_teaser(
    deltas: Sequence[SprintDelta],
    *,
    task_id: str | None,
    now: datetime,
    limit: int = 3,
) -> str:
    """≤ ``limit`` lines: recent beats on this task, surfacing open failures within 14 days."""
    if not deltas or limit < 1:
        return ""
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)

    scoped = _scope_deltas(deltas, task_id=task_id)
    ordered = sorted(scoped, key=recorded_at, reverse=True)
    picks: dict[str, SprintDelta] = {}

    if ordered:
        newest = ordered[0]
        if _include_in_teaser(newest, now=now):
            picks[newest.run_id] = newest

    for delta in ordered:
        age_days = (now - recorded_at(delta)).total_seconds() / 86_400.0
        if delta.outcome in _FAILURE_OUTCOMES and age_days <= RECENT_FAILURE_DAYS:
            picks[delta.run_id] = delta
            break

    for delta in ordered:
        if len(picks) >= limit:
            break
        if not _include_in_teaser(delta, now=now):
            continue
        picks.setdefault(delta.run_id, delta)

    lines = [_format_line(delta) for delta in sorted(picks.values(), key=recorded_at, reverse=True)]
    return "\n".join(lines[:limit])


def write_episodic_beat_start(
    harness_dir: Path,
    *,
    employee_id: str,
    task_id: str | None,
    teaser: str,
) -> None:
    """Persist the beat-start teaser for harness injection and e2e probes."""
    harness = harness_dir / ".harness"
    harness.mkdir(parents=True, exist_ok=True)
    payload = {
        "employee_id": employee_id,
        "task_id": task_id,
        "teaser": teaser,
    }
    path = harness / "episodic-beat-start.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _scope_deltas(deltas: Sequence[SprintDelta], *, task_id: str | None) -> list[SprintDelta]:
    if task_id:
        same_task = [delta for delta in deltas if delta.task_id == task_id]
        if same_task:
            return same_task
    return list(deltas)


def _format_line(delta: SprintDelta) -> str:
    prefix = delta.run_id[:12]
    hint = _OUTCOME_HINT.get(delta.outcome, "past beat")
    intent = delta.intent[:120].strip()
    return f"- [{delta.outcome}] {intent} ({prefix}…) — {hint}"


def _include_in_teaser(delta: SprintDelta, *, now: datetime) -> bool:
    if delta.outcome not in _FAILURE_OUTCOMES:
        return True
    age_days = (now - recorded_at(delta)).total_seconds() / 86_400.0
    return age_days <= RECENT_FAILURE_DAYS


__all__ = ["RECENT_FAILURE_DAYS", "build_episodic_teaser", "write_episodic_beat_start"]
