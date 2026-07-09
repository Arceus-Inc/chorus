"""Beat-start episodic teaser — R6."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from chorus.memory import SprintDelta
from chorus.memory._recall_teaser import build_episodic_teaser, write_episodic_beat_start

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 9, 12, 0, tzinfo=UTC)


def _delta(
    run_id: str,
    *,
    task_id: str = "t1",
    intent: str = "add slugify",
    outcome: str = "done",
    recorded_at: datetime,
) -> SprintDelta:
    return SprintDelta(
        run_id=run_id,
        task_id=task_id,
        employee_id="bex",
        scope="project",
        intent=intent,
        outcome=outcome,
        score=1.0,
        created_at=recorded_at,
        recorded_at=recorded_at,
    )


def test_empty_store_returns_empty_teaser() -> None:
    assert build_episodic_teaser((), task_id="t1", now=_NOW) == ""


def test_same_task_incomplete_surfaces_in_teaser() -> None:
    done = _delta("r_done", outcome="done", recorded_at=_NOW - timedelta(hours=2))
    incomplete = _delta(
        "r_inc",
        outcome="incomplete",
        intent="add truncate",
        recorded_at=_NOW - timedelta(hours=1),
    )
    teaser = build_episodic_teaser((done, incomplete), task_id="t1", now=_NOW)
    assert "incomplete" in teaser
    assert "truncate" in teaser
    assert "r_inc"[:12] in teaser


def test_cross_task_fallback_uses_global_recent() -> None:
    other = _delta(
        "r_other",
        task_id="t0",
        intent="add slugify helper",
        recorded_at=_NOW - timedelta(hours=1),
    )
    teaser = build_episodic_teaser((other,), task_id="t2", now=_NOW)
    assert "slugify" in teaser


def test_same_task_pool_preferred_over_global() -> None:
    old_other = _delta(
        "r_old",
        task_id="t0",
        intent="unrelated work",
        recorded_at=_NOW - timedelta(minutes=1),
    )
    same_task = _delta(
        "r_same",
        task_id="t1",
        intent="continue slugify",
        recorded_at=_NOW - timedelta(hours=2),
    )
    teaser = build_episodic_teaser((old_other, same_task), task_id="t1", now=_NOW)
    assert "slugify" in teaser
    assert "unrelated" not in teaser


def test_old_failure_not_promoted_outside_window() -> None:
    old_fail = _delta(
        "r_fail",
        outcome="needs_changes",
        intent="broken auth",
        recorded_at=_NOW - timedelta(days=20),
    )
    recent_done = _delta(
        "r_done",
        intent="add health check",
        recorded_at=_NOW - timedelta(hours=1),
    )
    teaser = build_episodic_teaser((old_fail, recent_done), task_id="t1", now=_NOW)
    assert "health check" in teaser
    assert "broken auth" not in teaser


def test_write_episodic_beat_start_json(tmp_path: Path) -> None:
    root = tmp_path / "wt"
    root.mkdir()
    write_episodic_beat_start(
        root,
        employee_id="bex",
        task_id="t1",
        teaser="- [done] add slugify (r_abc…) — finished",
    )
    path = root / ".harness" / "episodic-beat-start.json"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "bex" in text
    assert "slugify" in text
