"""RecallTool — the ``recall`` capability that closes the episodic loop (spec 07 §11).

The tool is the dream envelope around :class:`~chorus.memory.EpisodicStore`: it reads the calling
employee's identity from the per-beat :class:`~chorus.heartbeat.BeatContext` (never from model input,
so an employee can't be spoofed into reading another agent's history), then answers in one of two
modes — recency-only (no args: "what did I do lately") or keyword (``query``) — outcome-first, so a
returned past account always travels with its result (spec 06 §08 honesty: the prose is data, never a
directive).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger
from chorus.memory import EpisodicRecallService, EpisodicStore, SprintDelta
from chorus.testing import open_test_ledger, uid
from chorus_tools import RecallTool

pytestmark = pytest.mark.integration


def _tool(store: EpisodicStore) -> RecallTool:
    return RecallTool(EpisodicRecallService(store))


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _role_text_body(text: str) -> str:
    """A one-line raw_record JSONL body whose sole event is ``role.text`` — matches production shape."""
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id=uid("r_1"),
        task_id=uid("t_1"),
        employee_id="bex",
        scope="project",
        intent="add retry to the upload client",
        outcome="done",
        score=1.0,
        created_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        role="backend_engineer",
        recorded_at=datetime(2026, 6, 18, 12, 0, tzinfo=UTC),
        files_touched=("src/upload/client.py",),
        body=_role_text_body("bumped the pool size, retried on timeout"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def _beat(working_dir: Path, *, employee_id: str = "bex", run_id: str = uid("r_now")) -> None:
    BeatContext(task_id=uid("t_now"), run_id=run_id, employee_id=employee_id).write(working_dir)


async def test_recency_mode_returns_recent_records_for_this_employee(
    ledger: Ledger, tmp_path: Path
) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_old"), recorded_at=datetime(2026, 6, 1, tzinfo=UTC)))
    store.append(_delta(run_id=uid("r_new"), recorded_at=datetime(2026, 6, 20, tzinfo=UTC)))
    store.append(_delta(run_id=uid("r_other_agent"), employee_id="ada"))
    _beat(tmp_path)

    result = await _tool(store).execute({}, _ctx(tmp_path))

    assert result.is_error is False
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == [uid("r_new"), uid("r_old")]  # newest first, other agent excluded


async def test_recency_mode_excludes_the_current_run(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_now")))
    _beat(tmp_path, run_id=uid("r_now"))

    result = await _tool(store).execute({}, _ctx(tmp_path))

    assert (result.structured or {})["hits"] == []


async def test_query_mode_keyword_search(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_a"),
            intent="scaffold",
            body=_role_text_body(
                "Opened the form first. Later fixed retry timeout in the connection pool."
            ),
        )
    )
    store.append(
        _delta(run_id=uid("r_b"), intent="unrelated", body=_role_text_body("something else"))
    )
    _beat(tmp_path)

    result = await _tool(store).execute({"query": "retry timeout"}, _ctx(tmp_path))

    hits = (result.structured or {})["hits"]
    assert [hit["run_id"] for hit in hits] == [uid("r_a")]
    snip = str(hits[0].get("snippet") or "")
    assert "retry" in snip.lower()
    assert ">>>" in snip
    assert "snippet:" in result.content


async def test_hits_carry_summary_not_full_prose(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_a"),
            outcome="needs_changes",
            body=_role_text_body("tried the pool bump, regressed"),
        )
    )
    _beat(tmp_path)

    result = await _tool(store).execute({}, _ctx(tmp_path))

    hit = (result.structured or {})["hits"][0]
    assert hit["outcome"] == "needs_changes"
    assert "retry" in hit["intent"]
    assert "recorded_at" in hit
    assert "summary" in hit
    assert "prose" not in hit
    assert "drill_down" in hit
    assert "tried the pool bump" in hit["summary"]
    assert "get_run" in hit["drill_down"]


async def test_render_filters_noise_paths_from_files_touched(
    ledger: Ledger, tmp_path: Path
) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_noisy"),
            files_touched=(
                "auth/service.py",
                "TODO.md",
                "docs/exec-plans/active/run_x.md",
                "commerce.db",
                "tests/test_auth.py",
            ),
            body=_role_text_body("built salted password verify"),
        )
    )
    _beat(tmp_path)

    result = await _tool(store).execute({}, _ctx(tmp_path))
    hit = (result.structured or {})["hits"][0]
    assert hit["files_touched"] == ["auth/service.py", "tests/test_auth.py"]
    assert "docs/exec-plans" not in result.content
    assert "TODO.md" not in result.content
    assert "commerce.db" not in result.content
    assert "auth/service.py" in result.content


async def test_incomplete_outcome_is_labelled_for_resume(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_to"),
            outcome="incomplete",
            body=_role_text_body("mid-scaffold on auth register; tests not green yet"),
        )
    )
    _beat(tmp_path)

    result = await _tool(store).execute({}, _ctx(tmp_path))
    assert "incomplete" in result.content
    assert "resume" in result.content.lower() or "continue" in result.content.lower()


async def test_empty_result_is_not_an_error(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    _beat(tmp_path)
    result = await _tool(store).execute({}, _ctx(tmp_path))
    assert result.is_error is False
    assert (result.structured or {})["hits"] == []


async def test_limit_is_honoured(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    for i in range(5):
        store.append(_delta(run_id=uid(f"r_{i}"), recorded_at=datetime(2026, 6, 1 + i, tzinfo=UTC)))
    _beat(tmp_path)

    result = await _tool(store).execute({"limit": 2}, _ctx(tmp_path))

    assert len((result.structured or {})["hits"]) == 2


async def test_malformed_input_is_refused(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    _beat(tmp_path)
    result = await _tool(store).execute({"limit": 0}, _ctx(tmp_path))  # ge=1
    assert result.is_error is True
    structured = result.structured or {}
    assert structured["status"] == "error"
    assert "summary" in structured
    assert structured["next_actions"]
    assert structured["stop_condition"]


async def test_success_and_empty_carry_observation_contract(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a")))
    _beat(tmp_path)
    filled = await _tool(store).execute({}, _ctx(tmp_path))
    structured = filled.structured or {}
    assert structured["status"] == "success"
    assert "summary" in structured
    assert structured["next_actions"]
    assert "run_ids" in (structured.get("artifacts") or {})

    empty_store = EpisodicStore(open_test_ledger())
    _beat(tmp_path)
    empty = await _tool(empty_store).execute({}, _ctx(tmp_path))
    empty_s = empty.structured or {}
    assert empty_s["status"] == "empty"
    assert "summary" in empty_s
    assert empty_s["next_actions"] == ["proceed without prior history"]


async def test_recency_prefers_yesterday_over_old_failure(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_old_fail"),
            outcome="needs_changes",
            recorded_at=datetime(2026, 6, 1, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_recent_done"),
            recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
    )
    _beat(tmp_path)
    result = await _tool(store).execute({}, _ctx(tmp_path))
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids[0] == uid("r_recent_done")


async def test_keyword_search_is_employee_scoped(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_ada"), employee_id="ada", intent="retry timeout"))
    store.append(_delta(run_id=uid("r_bex"), employee_id="bex", intent="retry timeout"))
    _beat(tmp_path, employee_id="ada")
    result = await _tool(store).execute({"query": "retry"}, _ctx(tmp_path))
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == [uid("r_ada")]


async def test_recall_bumps_last_recalled_at(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a")))
    _beat(tmp_path)
    await _tool(store).execute({}, _ctx(tmp_path))
    got = store.get(uid("r_a"))
    assert got is not None
    assert got.last_recalled_at is not None


async def test_task_id_filter_on_recall(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_t1"), task_id=uid("t_1"), intent="slugify"))
    store.append(
        _delta(
            run_id=uid("r_t2"),
            task_id=uid("t_2"),
            intent="truncate",
            recorded_at=datetime(2026, 7, 9, tzinfo=UTC),
        )
    )
    _beat(tmp_path)
    result = await _tool(store).execute({"task_id": uid("t_1")}, _ctx(tmp_path))
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == [uid("r_t1")]
    assert (result.structured or {})["mode"] == "search"


async def test_since_filter_on_recall(ledger: Ledger, tmp_path: Path) -> None:
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
    _beat(tmp_path)
    result = await _tool(store).execute(
        {"task_id": uid("t_1"), "since": "2026-07-01T00:00:00+00:00"},
        _ctx(tmp_path),
    )
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == [uid("r_new")]


async def test_structured_mode_field(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a")))
    _beat(tmp_path)
    result = await _tool(store).execute({}, _ctx(tmp_path))
    assert (result.structured or {})["mode"] == "recency"
    assert (result.structured or {})["profile"] == "general"


async def test_debug_profile_refused_without_query_or_task_id(
    ledger: Ledger, tmp_path: Path
) -> None:
    store = EpisodicStore(ledger)
    _beat(tmp_path)
    result = await _tool(store).execute({"profile": "debug"}, _ctx(tmp_path))
    assert result.is_error is True
    assert "task_id" in result.content.lower()


async def test_debug_query_structured_profile_and_rank_note(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(
        _delta(
            run_id=uid("r_fail"),
            outcome="needs_changes",
            intent="slugify regression",
            body=_role_text_body("slugify regression"),
            recorded_at=datetime(2026, 7, 6, tzinfo=UTC),
        )
    )
    store.append(
        _delta(
            run_id=uid("r_ok"),
            outcome="done",
            intent="slugify works",
            body=_role_text_body("slugify works"),
            recorded_at=datetime(2026, 7, 8, tzinfo=UTC),
        )
    )
    _beat(tmp_path)
    result = await _tool(store).execute(
        {"query": "slugify", "profile": "debug"},
        _ctx(tmp_path),
    )
    structured = result.structured or {}
    assert structured["profile"] == "debug"
    top = structured["hits"][0]
    assert top["outcome"] == "needs_changes"
    assert "rank_note" in top
    assert "debug profile" in str(top["rank_note"])
    assert any("failed previously" in action for action in structured["next_actions"])
