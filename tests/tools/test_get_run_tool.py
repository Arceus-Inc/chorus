"""GetRunTool — full prose drill-down for one episodic beat (R8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta
from chorus.memory._recall_service import EpisodicRecallService
from chorus_tools._get_run import GetRunTool

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _body(text: str) -> str:
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
        body=_body("bumped the pool size, retried on timeout"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def _beat(working_dir: Path, *, employee_id: str = "bex", run_id: str = "r_now") -> None:
    BeatContext(task_id="t_now", run_id=run_id, employee_id=employee_id).write(working_dir)


async def test_get_run_returns_full_prose(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(_delta(run_id="r_a", body=_body("full beat narrative here")))
    svc = EpisodicRecallService(store)
    _beat(tmp_path)

    result = await GetRunTool(svc).execute({"run_id": "r_a"}, _ctx(tmp_path))

    assert result.is_error is False
    assert "full beat narrative here" in result.content
    assert (result.structured or {})["run_id"] == "r_a"


async def test_get_run_rejects_cross_employee(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    store.append(_delta(run_id="r_a", employee_id="ada"))
    svc = EpisodicRecallService(store)
    _beat(tmp_path, employee_id="bex")

    result = await GetRunTool(svc).execute({"run_id": "r_a"}, _ctx(tmp_path))

    assert result.is_error is True
    assert "refused" in result.content


async def test_get_run_missing_run_id(tmp_path: Path) -> None:
    store = EpisodicStore(tmp_path / "memory")
    svc = EpisodicRecallService(store)
    _beat(tmp_path)

    result = await GetRunTool(svc).execute({"run_id": "r_missing"}, _ctx(tmp_path))

    assert result.is_error is True
