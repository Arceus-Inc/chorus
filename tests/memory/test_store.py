"""EpisodicStore — the SQLite-native episodic record store (replaces the md writer).

The source of truth is now a per-org SQLite file: an append-only ``episodic_record`` table
(immutable = the audit trail) with ``files_touched`` stored inline, and an FTS5 index over
intent+body (BM25 search). One record per beat, first-write-wins.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from chorus.memory import EpisodicStore, SprintDelta

pytestmark = pytest.mark.integration  # touches sqlite on disk


def _role_text_body(text: str) -> str:
    """A one-line raw_record JSONL body whose sole event is ``role.text`` — matches production shape."""
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id="r_1",
        task_id="t_1",
        employee_id="ada",
        scope="project",
        intent="add retry to the upload client",
        outcome="done",
        score=0.83,
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        role="backend_engineer",
        recorded_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        artifacts=("pr:org/repo#214",),
        files_touched=("src/upload/client.py", "tests/test_upload.py"),
        body=_role_text_body("bumped the pool size, retried"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def test_append_then_get_round_trips_the_record(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta())
    got = store.get("r_1")
    assert got is not None
    assert got.run_id == "r_1"
    assert got.employee_id == "ada"
    assert got.role == "backend_engineer"
    assert got.outcome == "done"
    assert got.score == 0.83
    assert got.files_touched == ("src/upload/client.py", "tests/test_upload.py")
    assert got.artifacts == ("pr:org/repo#214",)
    assert "bumped the pool size" in got.body


def test_get_missing_is_none(tmp_path) -> None:
    assert EpisodicStore(tmp_path).get("nope") is None


def test_append_is_idempotent_first_write_wins(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(body="first"))
    store.append(_delta(body="second"))  # same run_id — append-only no-op
    got = store.get("r_1")
    assert got is not None and got.body == "first"
    assert store.count() == 1


def test_records_partitioned_and_listable_per_agent(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_a", employee_id="ada"))
    store.append(_delta(run_id="r_b", employee_id="ada"))
    store.append(_delta(run_id="r_c", employee_id="bex"))
    ada = {d.run_id for d in store.records_for("ada")}
    assert ada == {"r_a", "r_b"}
    assert {d.run_id for d in store.records_for("bex")} == {"r_c"}


def test_persists_across_reopen(tmp_path) -> None:
    EpisodicStore(tmp_path).append(_delta())
    reopened = EpisodicStore(tmp_path)  # same dir → same episodic.db
    assert reopened.get("r_1") is not None


def test_search_matches_the_indexed_intent_and_body(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(
        _delta(
            run_id="r_a",
            intent="add retry to the upload client",
            body=_role_text_body("bumped pool size"),
        )
    )
    store.append(
        _delta(
            run_id="r_b", intent="unrelated task", body=_role_text_body("unrelated work entirely")
        )
    )
    hits = store.search("retry")
    assert [d.run_id for d in hits] == ["r_a"]


def test_search_ranks_the_stronger_match_first(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta(run_id="r_weak", intent="x", body=_role_text_body("mentions retry once")))
    store.append(
        _delta(
            run_id="r_strong",
            intent="retry retry retry",
            body=_role_text_body("retry retry retry retry"),
        )
    )
    hits = store.search("retry")
    assert [d.run_id for d in hits] == ["r_strong", "r_weak"]


def test_search_respects_limit(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    for i in range(5):
        store.append(_delta(run_id=f"r_{i}", intent="retry", body=_role_text_body("retry")))
    assert len(store.search("retry", limit=2)) == 2


def test_search_no_match_is_empty(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(_delta())
    assert store.search("xyzzy_nonexistent") == []


def test_search_multi_word_requires_all_terms_and(tmp_path) -> None:
    """Implicit AND: both tokens must appear — OR-soup used to match either term."""
    store = EpisodicStore(tmp_path)
    store.append(
        _delta(
            run_id="r_both",
            intent="retry upload client",
            body=_role_text_body("retry on upload timeout"),
        )
    )
    store.append(
        _delta(
            run_id="r_one",
            intent="retry alone",
            body=_role_text_body("retry once without the other token"),
        )
    )
    hits = store.search("retry upload")
    assert [d.run_id for d in hits] == ["r_both"]


def test_search_indexes_normalized_narrative_without_tags(tmp_path) -> None:
    store = EpisodicStore(tmp_path)
    store.append(
        _delta(
            run_id="r_tagged",
            intent="cleanup",
            body=_role_text_body("<spec>implement slugify helper</spec>"),
        )
    )
    assert [d.run_id for d in store.search("slugify")] == ["r_tagged"]
    assert [d.run_id for d in store.search("spec")] == []
