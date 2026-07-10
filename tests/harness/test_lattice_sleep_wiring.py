"""Sleep beat wiring — adjudicate at materialize, forget after apply."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from chorus.roles import RoleRegistry, default_roles
from chorus.workforce import Employee
from chorus_harness import _factory as _factory_mod
from chorus_tools._lattice import LatticeApplyTool
from chorus_tools._lattice_bridge import build_lattice_for_chorus
from dream.tools._context import ToolExecutionContext

from chorus.heartbeat import BeatContext
from chorus.memory import EpisodicStore, SprintDelta

pytestmark = pytest.mark.integration


@dataclass
class _RecordingLattice:
    adjudicate_calls: list[str] = field(default_factory=list)
    forget_calls: list[str] = field(default_factory=list)
    gate_open: bool = True

    def has_fresh_episodes(self, employee_id: str) -> bool:
        return True

    def adjudicate(self, employee_id: str) -> Any:
        self.adjudicate_calls.append(employee_id)
        return MagicMock(atoms_updated=1, episodes_processed=1)

    def forget(self, employee_id: str) -> Any:
        self.forget_calls.append(employee_id)
        return MagicMock(atoms_discounted=1, atoms_invalidated=0)

    def apply(self, proposal: Any) -> Any:
        return MagicMock(ok=True, patterns_written=1, errors=())

    def validate(self, proposal: Any) -> Any:
        return MagicMock(ok=True, errors=())


def _factory(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, lattice: _RecordingLattice) -> Any:
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        _factory_mod.dream, "build_harness", lambda **kw: captured.update(kw) or object()
    )
    monkeypatch.setattr(
        _factory_mod,
        "build_lattice_for_chorus",
        lambda *_args, **_kwargs: lattice,
    )
    return _factory_mod.EmployeeHarnessFactory(
        api_key="k",
        base_url="https://x/openai/v1",
        deployment="gpt-x",
        company_id="acme",
        roles=RoleRegistry.from_plugins(default_roles()),
        work_root=tmp_path,
    )


def test_materialize_calls_adjudicate_when_fresh_episodes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    lattice = _RecordingLattice()
    factory = _factory(monkeypatch, tmp_path, lattice)
    factory.materialize(Employee(id="bex", name="Bex", role="backend_engineer"))
    assert lattice.adjudicate_calls == ["bex"]


def _ctx(working_dir: Path) -> ToolExecutionContext:
    return ToolExecutionContext(working_dir=working_dir, session_id="sess")


@pytest.mark.asyncio
async def test_apply_calls_forget_after_success(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    company = tmp_path / "acme"
    store = EpisodicStore(company / "memory")
    now = datetime.now(UTC)
    store.append(
        SprintDelta(
            run_id="r1",
            task_id="t1",
            employee_id="bex",
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
    )
    lattice = build_lattice_for_chorus(company, min_new_episodes=1, min_cluster_size=1)
    tool = LatticeApplyTool(lattice)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    BeatContext(employee_id="bex", run_id="run_a", task_id="t1").write(worktree)

    result = await tool.execute(
        {
            "proposal": {
                "patterns": [
                    {
                        "key": "api.retry",
                        "claim": "HTTP client retries use exponential backoff capped at 30s",
                        "source_run_ids": ["r1"],
                    }
                ],
            }
        },
        _ctx(worktree),
    )
    assert result.is_error is False
    assert "forget discounted=" in result.content
    assert lattice.gate_open("bex") is False
