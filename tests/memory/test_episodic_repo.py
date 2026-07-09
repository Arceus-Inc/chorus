"""EpisodicRepo — bounded SQL reads and retention metadata (R0 + R2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from chorus.memory import EpisodicStore, SprintDelta

pytestmark = pytest.mark.integration


def _role_text_body(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id="r_1",
        task_id="t_1",
        employee_id="ada",
        scope="project",
        intent="add retry",
        outcome="done",
        score=1.0,
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        role="backend_engineer",
        recorded_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        body=_role_text_body("retry work"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def test_for_employee_limit_returns_newest_only(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(50):
        store.append(
            _delta(
                run_id=f"r_{i:02d}",
                recorded_at=base + timedelta(days=i),
            )
        )
    hits = store.records_for("ada", limit=5)
    assert [d.run_id for d in hits] == ["r_49", "r_48", "r_47", "r_46", "r_45"]


def test_search_scoped_to_employee(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_ada", employee_id="ada", intent="retry timeout"))
    store.append(_delta(run_id="r_bex", employee_id="bex", intent="retry timeout"))
    ada_hits = store.search("retry", employee_id="ada", limit=5)
    assert [d.run_id for d in ada_hits] == ["r_ada"]


def test_touch_recalled_sets_timestamp(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_a"))
    now = datetime(2026, 7, 9, 8, 0, tzinfo=UTC)
    store.touch_recalled(("r_a",), now=now)
    got = store.get("r_a")
    assert got is not None
    assert got.last_recalled_at == now


def test_pin_run_ids_increments_for_employee(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_a", employee_id="ada"))
    store.append(_delta(run_id="r_b", employee_id="ada"))
    store.pin_run_ids("ada", ("r_a", "r_b"))
    store.pin_run_ids("ada", ("r_a",))
    assert store.get("r_a") is not None and store.get("r_a").pin_count == 2
    assert store.get("r_b") is not None and store.get("r_b").pin_count == 1


def test_pin_ignores_other_employees(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_a", employee_id="ada"))
    store.pin_run_ids("bex", ("r_a",))
    got = store.get("r_a")
    assert got is not None and got.pin_count == 0


def test_for_employee_since_filter(tmp_path) -> None:
    from datetime import UTC, datetime

    from chorus.memory._recall_filters import EpisodicQueryFilters

    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_old", recorded_at=datetime(2026, 6, 1, tzinfo=UTC)))
    store.append(_delta(run_id="r_new", recorded_at=datetime(2026, 7, 8, tzinfo=UTC)))
    hits = store.records_for(
        "ada",
        limit=5,
        filters=EpisodicQueryFilters(since=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    assert [d.run_id for d in hits] == ["r_new"]


def test_for_employee_task_id_filter(tmp_path) -> None:
    from chorus.memory._recall_filters import EpisodicQueryFilters

    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_1", task_id="t_1"))
    store.append(_delta(run_id="r_2", task_id="t_2"))
    hits = store.records_for("ada", limit=5, filters=EpisodicQueryFilters(task_id="t_1"))
    assert [d.run_id for d in hits] == ["r_1"]
