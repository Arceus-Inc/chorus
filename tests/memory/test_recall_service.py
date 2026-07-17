"""EpisodicRecallService — list/search/get_run kernel (R7 + R8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from chorus.ledger import Ledger
from chorus.memory import EpisodicQueryFilters, EpisodicRecallService, EpisodicStore, SprintDelta
from chorus.testing import uid

pytestmark = pytest.mark.integration


def _body(text: str) -> str:
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id=uid("r_1"),
        task_id=uid("t_1"),
        employee_id="bex",
        scope="project",
        intent="add retry",
        outcome="done",
        score=1.0,
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        role="backend_engineer",
        recorded_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        body=_body("did retry work"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def test_recency_mode_without_filters(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_old"), recorded_at=datetime(2026, 6, 1, tzinfo=UTC)))
    store.append(_delta(run_id=uid("r_new"), recorded_at=datetime(2026, 6, 20, tzinfo=UTC)))
    svc = EpisodicRecallService(store)
    result = svc.recall(
        "bex", own_run_id=uid("r_now"), limit=5, now=datetime(2026, 7, 9, tzinfo=UTC)
    )
    assert result.mode == "recency"
    assert [d.run_id for d in result.hits] == [uid("r_new"), uid("r_old")]


def test_since_filter_scopes_task_thread(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_old"),
            task_id=uid("t_1"),
            recorded_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_new"),
            task_id=uid("t_1"),
            recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
    )
    svc = EpisodicRecallService(store)
    result = svc.recall(
        "bex",
        own_run_id=uid("r_now"),
        filters=EpisodicQueryFilters(
            task_id=uid("t_1"),
            since=datetime(2026, 7, 1, tzinfo=UTC),
        ),
        limit=5,
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )
    assert result.mode == "search"
    assert [d.run_id for d in result.hits] == [uid("r_new")]


def test_task_id_filter_scopes_recency(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_t2"),
            task_id=uid("t_2"),
            intent="truncate",
            recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_t1"),
            task_id=uid("t_1"),
            intent="slugify",
            recorded_at=datetime(2026, 7, 1, tzinfo=UTC),
        )
    )
    svc = EpisodicRecallService(store)
    result = svc.recall(
        "bex",
        own_run_id=uid("r_now"),
        filters=EpisodicQueryFilters(task_id=uid("t_1")),
        limit=5,
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )
    assert [d.run_id for d in result.hits] == [uid("r_t1")]


def test_debug_query_promotes_failure(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_ok"),
            outcome="done",
            intent="slugify works",
            body=_body("slugify works"),
            recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_fail"),
            outcome="needs_changes",
            intent="slugify regression",
            body=_body("slugify regression failed"),
            recorded_at=datetime(2026, 7, 6, tzinfo=UTC),
        )
    )
    svc = EpisodicRecallService(store)
    result = svc.recall(
        "bex",
        own_run_id=uid("r_now"),
        query="slugify regression",
        profile="debug",
        limit=5,
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )
    assert result.profile == "debug"
    assert result.mode == "search"
    assert result.hits[0].run_id == uid("r_fail")


def test_debug_task_thread_promotes_failure(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_ok"),
            task_id=uid("t_1"),
            outcome="done",
            recorded_at=datetime(2026, 7, 8, 12, 0, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_fail"),
            task_id=uid("t_1"),
            outcome="needs_changes",
            recorded_at=datetime(2026, 7, 8, 10, 0, tzinfo=UTC),
        )
    )
    svc = EpisodicRecallService(store)
    result = svc.recall(
        "bex",
        own_run_id=uid("r_now"),
        profile="debug",
        filters=EpisodicQueryFilters(task_id=uid("t_1")),
        limit=5,
        now=datetime(2026, 7, 9, tzinfo=UTC),
    )
    assert result.profile == "debug"
    assert [d.run_id for d in result.hits] == [uid("r_fail"), uid("r_ok")]


def test_get_run_rejects_cross_employee(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), employee_id="ada"))
    svc = EpisodicRecallService(store)
    assert svc.get_run("bex", uid("r_a")) is None


def test_get_run_returns_full_record(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), body=_body("full narrative prose here")))
    svc = EpisodicRecallService(store)
    got = svc.get_run("bex", uid("r_a"))
    assert got is not None
    assert "full narrative prose here" in got.body
