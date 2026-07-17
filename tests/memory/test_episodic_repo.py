"""EpisodicRepo — bounded SQL reads and retention metadata (R0 + R2)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import Ledger
from chorus.memory import EpisodicStore, SprintDelta
from chorus.testing import uid

pytestmark = pytest.mark.integration


def _role_text_body(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id=uid("r_1"),
        task_id=uid("t_1"),
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


def test_for_employee_limit_returns_newest_only(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(50):
        store.append(
            _delta(
                run_id=uid(f"r_{i:02d}"),
                recorded_at=base + timedelta(days=i),
            )
        )
    hits = store.records_for("ada", limit=5)
    assert [d.run_id for d in hits] == [uid(f"r_{i:02d}") for i in range(49, 44, -1)]


def test_search_scoped_to_employee(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_ada"), employee_id="ada", intent="retry timeout"))
    store.append(_delta(run_id=uid("r_bex"), employee_id="bex", intent="retry timeout"))
    ada_hits = store.search("retry", employee_id="ada", limit=5)
    assert [h.record.run_id for h in ada_hits] == [uid("r_ada")]


def test_touch_recalled_sets_timestamp(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a")))
    now = datetime(2026, 7, 9, 8, 0, tzinfo=UTC)
    store.touch_recalled((uid("r_a"),), now=now)
    got = store.get(uid("r_a"))
    assert got is not None
    assert got.last_recalled_at == now


def test_pin_run_ids_increments_for_employee(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), employee_id="ada"))
    store.append(_delta(run_id=uid("r_b"), employee_id="ada"))
    store.pin_run_ids("ada", (uid("r_a"), uid("r_b")))
    store.pin_run_ids("ada", (uid("r_a"),))
    assert store.get(uid("r_a")) is not None and store.get(uid("r_a")).pin_count == 2
    assert store.get(uid("r_b")) is not None and store.get(uid("r_b")).pin_count == 1


def test_pin_ignores_other_employees(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), employee_id="ada"))
    store.pin_run_ids("bex", (uid("r_a"),))
    got = store.get(uid("r_a"))
    assert got is not None and got.pin_count == 0


def test_for_employee_since_filter(ledger: Ledger) -> None:
    from datetime import UTC, datetime

    from chorus.memory import EpisodicQueryFilters

    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_old"), recorded_at=datetime(2026, 6, 1, tzinfo=UTC)))
    store.append(_delta(run_id=uid("r_new"), recorded_at=datetime(2026, 7, 8, tzinfo=UTC)))
    hits = store.records_for(
        "ada",
        limit=5,
        filters=EpisodicQueryFilters(since=datetime(2026, 7, 1, tzinfo=UTC)),
    )
    assert [d.run_id for d in hits] == [uid("r_new")]


def test_for_employee_task_id_filter(ledger: Ledger) -> None:
    from chorus.memory import EpisodicQueryFilters

    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_1"), task_id=uid("t_1")))
    store.append(_delta(run_id=uid("r_2"), task_id=uid("t_2")))
    hits = store.records_for("ada", limit=5, filters=EpisodicQueryFilters(task_id=uid("t_1")))
    assert [d.run_id for d in hits] == [uid("r_1")]
