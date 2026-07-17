"""GetRunTool — full prose drill-down for one episodic beat (R8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger
from chorus.memory import EpisodicRecallService, EpisodicStore, SprintDelta
from chorus.testing import uid
from chorus_tools._get_run import GetRunInput, GetRunTool

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _body(text: str) -> str:
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
        body=_body("bumped the pool size, retried on timeout"),
    )
    base.update(over)
    return SprintDelta(**base)  # type: ignore[arg-type]


def _beat(working_dir: Path, *, employee_id: str = "bex", run_id: str = "r_now") -> None:
    BeatContext(task_id=uid("t_now"), run_id=run_id, employee_id=employee_id).write(working_dir)


async def test_get_run_returns_full_prose(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), body=_body("full beat narrative here")))
    svc = EpisodicRecallService(store)
    _beat(tmp_path)

    result = await GetRunTool(svc).execute({"run_id": uid("r_a")}, _ctx(tmp_path))

    assert result.is_error is False
    assert "full beat narrative here" in result.content
    structured = result.structured or {}
    assert structured["status"] == "success"
    assert structured["run_id"] == uid("r_a")
    assert "summary" in structured
    assert structured["next_actions"]
    assert "run_id" in (structured.get("artifacts") or {})


async def test_get_run_rejects_cross_employee(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    store.append(_delta(run_id=uid("r_a"), employee_id="ada"))
    svc = EpisodicRecallService(store)
    _beat(tmp_path, employee_id="bex")

    result = await GetRunTool(svc).execute({"run_id": uid("r_a")}, _ctx(tmp_path))

    assert result.is_error is True
    assert "refused" in result.content
    structured = result.structured or {}
    assert structured["status"] == "error"
    assert structured["next_actions"]
    assert structured["stop_condition"]


async def test_get_run_missing_run_id(ledger: Ledger, tmp_path: Path) -> None:
    store = EpisodicStore(ledger)
    svc = EpisodicRecallService(store)
    _beat(tmp_path)

    result = await GetRunTool(svc).execute({"run_id": uid("r_missing")}, _ctx(tmp_path))

    assert result.is_error is True
    structured = result.structured or {}
    assert structured["status"] == "error"
    assert any("recall" in action for action in structured["next_actions"])


async def test_get_run_copy_does_not_mention_teaser() -> None:
    assert "teaser" not in GetRunTool.description.lower()
    assert "teaser" not in GetRunInput.model_fields["run_id"].description.lower()
