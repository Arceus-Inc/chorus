"""E2E-12 — lattice_apply rejects cross-employee proposal ids."""

from __future__ import annotations

from pathlib import Path

import pytest
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta
from chorus.testing import uid
from chorus_tools._lattice import LatticeApplyTool
from chorus_tools._lattice_bridge import build_lattice_for_chorus

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


def _delta(run_id: str, *, employee_id: str = "bex") -> SprintDelta:
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    return SprintDelta(
        run_id=run_id,
        task_id=uid("t1"),
        employee_id=employee_id,
        role="backend_engineer",
        scope="project",
        intent="retry",
        outcome="done",
        score=1.0,
        created_at=now,
        recorded_at=now,
        artifacts=(),
        files_touched=("src/api/client.py",),
        body="beat",
    )


@pytest.mark.asyncio
async def test_lattice_apply_rejects_cross_employee_id(tmp_path: Path) -> None:
    company = tmp_path / "acme"
    store = EpisodicStore(company / "memory")
    store.append(_delta("r1"))
    lattice = build_lattice_for_chorus(company, min_new_episodes=1, min_cluster_size=1)
    tool = LatticeApplyTool(lattice)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    BeatContext(employee_id="bex", run_id=uid("run_a"), task_id=uid("t1")).write(worktree)

    result = await tool.execute(
        {
            "proposal": {
                "employee_id": uid("other_emp"),
                "patterns": [
                    {
                        "key": "api.retry",
                        "claim": "HTTP retries use exponential backoff capped at 30s",
                        "source_run_ids": ["r1"],
                    }
                ],
            }
        },
        _ctx(worktree),
    )
    assert result.is_error is True
    assert "cross-employee" in result.content


@pytest.mark.asyncio
async def test_lattice_context_repeat_call_returns_unchanged_note(tmp_path: Path) -> None:
    """A second identical query whose patterns did not change returns a short cached note.

    The live 5+2 probe showed 5 identical lattice_context calls in one beat, each re-spending the
    tokens of the full pattern block — the tool memoises per (query, limit) within a materialize.
    """
    from chorus_tools._lattice import LatticeContextTool

    company = tmp_path / "acme"
    store = EpisodicStore(company / "memory")
    store.append(_delta("r1"))
    lattice = build_lattice_for_chorus(company, min_new_episodes=1, min_cluster_size=1)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    BeatContext(employee_id="bex", run_id=uid("run_a"), task_id=uid("t1")).write(worktree)

    apply_result = await LatticeApplyTool(lattice).execute(
        {
            "proposal": {
                "employee_id": "bex",
                "patterns": [
                    {
                        "key": "api.retry",
                        "claim": "HTTP retries use exponential backoff capped at 30s",
                        "source_run_ids": ["r1"],
                    }
                ],
            }
        },
        _ctx(worktree),
    )
    assert apply_result.is_error is not True

    tool = LatticeContextTool(lattice)
    first = await tool.execute({"query": "retry"}, _ctx(worktree))
    assert (first.structured or {}).get("status") == "success"
    assert "exponential backoff" in first.content

    second = await tool.execute({"query": "retry"}, _ctx(worktree))
    assert (second.structured or {}).get("cached") is True
    assert "unchanged" in second.content
    assert "exponential backoff" not in second.content  # the full block is NOT re-rendered

    # A different query is not deduped.
    other = await tool.execute({"query": "retry", "limit": 3}, _ctx(worktree))
    assert (other.structured or {}).get("cached") is not True
