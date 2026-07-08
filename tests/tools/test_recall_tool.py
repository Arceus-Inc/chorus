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
from chorus.memory import EpisodicStore, SprintDelta
from chorus_tools import RecallTool

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _role_text_body(text: str) -> str:
    """A one-line raw_record JSONL body whose sole event is ``role.text`` — matches production shape."""
    return json.dumps({"kind": "role.text", "role": "generator", "text": text})


def _delta(**over: object) -> SprintDelta:
    base: dict[str, object] = dict(
        run_id="r_1",
        task_id="t_1",
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


def _beat(working_dir: Path, *, employee_id: str = "bex", run_id: str = "r_now") -> None:
    BeatContext(task_id="t_now", run_id=run_id, employee_id=employee_id).write(working_dir)


async def test_recency_mode_returns_recent_records_for_this_employee(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(_delta(run_id="r_old", recorded_at=datetime(2026, 6, 1, tzinfo=UTC)))
    store.append(_delta(run_id="r_new", recorded_at=datetime(2026, 6, 20, tzinfo=UTC)))
    store.append(_delta(run_id="r_other_agent", employee_id="ada"))
    _beat(tmp_path)

    result = await RecallTool(store).execute({}, _ctx(tmp_path))

    assert result.is_error is False
    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == ["r_new", "r_old"]  # newest first, other agent excluded


async def test_recency_mode_excludes_the_current_run(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(_delta(run_id="r_now"))
    _beat(tmp_path, run_id="r_now")

    result = await RecallTool(store).execute({}, _ctx(tmp_path))

    assert (result.structured or {})["hits"] == []


async def test_query_mode_keyword_search(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(_delta(run_id="r_a", intent="fix the retry logic", body="retry retry retry"))
    store.append(_delta(run_id="r_b", intent="unrelated", body="something else entirely"))
    _beat(tmp_path)

    result = await RecallTool(store).execute({"query": "retry"}, _ctx(tmp_path))

    ids = [hit["run_id"] for hit in (result.structured or {})["hits"]]
    assert ids == ["r_a"]


async def test_hits_carry_the_outcome_and_a_prose_snippet(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(
        _delta(
            run_id="r_a",
            outcome="needs_changes",
            body=_role_text_body("tried the pool bump, regressed"),
        )
    )
    _beat(tmp_path)

    result = await RecallTool(store).execute({}, _ctx(tmp_path))

    hit = (result.structured or {})["hits"][0]
    assert hit["outcome"] == "needs_changes"
    assert "retry" in hit["intent"]
    assert "recorded_at" in hit
    assert "tried the pool bump" in hit["prose"]
    # text content also carries prose — agents often only read content, not structured
    assert "tried the pool bump" in result.content


async def test_render_filters_noise_paths_from_files_touched(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(
        _delta(
            run_id="r_noisy",
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

    result = await RecallTool(store).execute({}, _ctx(tmp_path))
    hit = (result.structured or {})["hits"][0]
    assert hit["files_touched"] == ["auth/service.py", "tests/test_auth.py"]
    assert "docs/exec-plans" not in result.content
    assert "TODO.md" not in result.content
    assert "commerce.db" not in result.content
    assert "auth/service.py" in result.content


async def test_incomplete_outcome_is_labelled_for_resume(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(
        _delta(
            run_id="r_to",
            outcome="incomplete",
            body=_role_text_body("mid-scaffold on auth register; tests not green yet"),
        )
    )
    _beat(tmp_path)

    result = await RecallTool(store).execute({}, _ctx(tmp_path))
    assert "incomplete" in result.content
    assert "resume" in result.content.lower() or "continue" in result.content.lower()


async def test_empty_result_is_not_an_error(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    _beat(tmp_path)
    result = await RecallTool(store).execute({}, _ctx(tmp_path))
    assert result.is_error is False
    assert (result.structured or {})["hits"] == []


async def test_limit_is_honoured(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    for i in range(5):
        store.append(_delta(run_id=f"r_{i}", recorded_at=datetime(2026, 6, 1 + i, tzinfo=UTC)))
    _beat(tmp_path)

    result = await RecallTool(store).execute({"limit": 2}, _ctx(tmp_path))

    assert len((result.structured or {})["hits"]) == 2


async def test_malformed_input_is_refused(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    _beat(tmp_path)
    result = await RecallTool(store).execute({"limit": 0}, _ctx(tmp_path))  # ge=1
    assert result.is_error is True
