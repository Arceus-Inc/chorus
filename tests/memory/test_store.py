"""EpisodicStore — the SQLite-native episodic record store (replaces the md writer).

The source of truth is now a per-org SQLite file: an append-only ``episodic_record`` table
(immutable = the audit trail) with ``files_touched`` stored inline, and an FTS5 index over
intent+body (BM25 search). One record per beat, first-write-wins.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from chorus.ledger import Ledger
from chorus.memory import EpisodicStore, SprintDelta
from chorus.testing import uid

pytestmark = pytest.mark.integration


def _role_text_body(text: str) -> str:
    """A one-line raw_record JSONL body whose sole event is ``role.text`` — matches production shape."""
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id=uid("r_1"),
        task_id=uid("t_1"),
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


def test_append_then_get_round_trips_the_record(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta())
    got = store.get(uid("r_1"))
    assert got is not None
    assert got.run_id == uid("r_1")
    assert got.employee_id == "ada"
    assert got.role == "backend_engineer"
    assert got.outcome == "done"
    assert got.score == 0.83
    assert got.files_touched == ("src/upload/client.py", "tests/test_upload.py")
    assert got.artifacts == ("pr:org/repo#214",)
    assert "bumped the pool size" in got.body


def test_get_missing_is_none(ledger: Ledger) -> None:
    assert EpisodicStore(ledger).get(uid("nope")) is None


def test_append_is_idempotent_first_write_wins(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(body="first"))
    store.append(_delta(body="second"))  # same run_id — append-only no-op
    got = store.get(uid("r_1"))
    assert got is not None and got.body == "first"
    assert store.count() == 1


def test_records_partitioned_and_listable_per_agent(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), employee_id="ada"))
    store.append(_delta(run_id=uid("r_b"), employee_id="ada"))
    store.append(_delta(run_id=uid("r_c"), employee_id="bex"))
    ada = {d.run_id for d in store.records_for("ada")}
    assert ada == {uid("r_a"), uid("r_b")}
    assert {d.run_id for d in store.records_for("bex")} == {uid("r_c")}


def test_persists_across_reopen(ledger: Ledger) -> None:
    EpisodicStore(ledger).append(_delta())
    reopened = EpisodicStore(ledger)  # same database + company → same rows
    assert reopened.get(uid("r_1")) is not None


def test_search_matches_the_indexed_intent_and_body(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_a"),
            intent="add retry to the upload client",
            body=_role_text_body("bumped pool size"),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_b"),
            intent="unrelated task",
            body=_role_text_body("unrelated work entirely"),
        )
    )
    hits = store.search("retry")
    assert [h.record.run_id for h in hits] == [uid("r_a")]


def test_search_ranks_the_stronger_match_first(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(run_id=uid("r_weak"), intent="x", body=_role_text_body("mentions retry once"))
    )
    store.append(
        _delta(
            run_id=uid("r_strong"),
            intent="retry retry retry",
            body=_role_text_body("retry retry retry retry"),
        )
    )
    hits = store.search("retry")
    assert [h.record.run_id for h in hits] == [uid("r_strong"), uid("r_weak")]


def test_search_respects_limit(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    for i in range(5):
        store.append(_delta(run_id=uid(f"r_{i}"), intent="retry", body=_role_text_body("retry")))
    assert len(store.search("retry", limit=2)) == 2


def test_search_no_match_is_empty(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta())
    assert store.search("xyzzy_nonexistent") == []


def test_search_multi_word_requires_all_terms_and(ledger: Ledger) -> None:
    """Implicit AND: both tokens must appear — OR-soup used to match either term."""
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_both"),
            intent="retry upload client",
            body=_role_text_body("retry on upload timeout"),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_one"),
            intent="retry alone",
            body=_role_text_body("retry once without the other token"),
        )
    )
    hits = store.search("retry upload")
    assert [h.record.run_id for h in hits] == [uid("r_both")]


def test_search_indexes_normalized_narrative_without_tags(ledger: Ledger) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_tagged"),
            intent="cleanup",
            body=_role_text_body("<spec>implement slugify helper</spec>"),
        )
    )
    assert [h.record.run_id for h in store.search("slugify")] == [uid("r_tagged")]
    assert [h.record.run_id for h in store.search("spec")] == []


def test_search_snippet_marks_match_in_body_not_first_sentence(ledger: Ledger) -> None:
    """Query teaser is FTS5 snippet around the match, not beat opener."""
    store = EpisodicStore(ledger)
    opener = "Started the register form and sketched the empty layout."
    filler = " ".join(f"pad{i}" for i in range(40))
    match = "Much later fixed the retry on timeout in the pool."
    store.append(
        _delta(
            run_id=uid("r_mid"),
            intent="scaffold auth",
            body=_role_text_body(f"{opener} {filler} {match}"),
        )
    )
    hits = store.search("retry timeout")
    assert len(hits) == 1
    assert hits[0].record.run_id == uid("r_mid")
    snip = hits[0].snippet.lower()
    assert "retry" in snip
    assert ">>>" in hits[0].snippet
    assert "started the register" not in snip
