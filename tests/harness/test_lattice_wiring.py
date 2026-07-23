"""E2E-13 / E2E-14 — scheduler lattice teaser + resilience."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome
from chorus.heartbeat._scheduler import Scheduler
from chorus.ledger import Task, TaskPriority, TaskStatus
from chorus.memory import EpisodicStore, SprintDelta
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _employee() -> Employee:
    return Employee(id="bex", name="Bex", role="backend_engineer")


def _task() -> Task:
    return Task(
        id=uid("task_1"),
        intent="add retry",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.MEDIUM,
        assignee="bex",
        depth=0,
    )


def _outcome() -> BeatOutcome:
    return BeatOutcome(passed=True, disposition=BeatDisposition.DONE, summary="ok")


def _append_cluster(store: EpisodicStore, *, n: int = 5) -> None:
    now = datetime.now(UTC)
    for i in range(n):
        store.append(
            SprintDelta(
                run_id=f"r_{i}",
                task_id=uid("t1"),
                employee_id="bex",
                role="backend_engineer",
                scope="project",
                intent="add retry",
                outcome="done",
                score=1.0,
                created_at=now,
                recorded_at=now,
                artifacts=(),
                files_touched=("src/api/client.py",),
                body="beat",
            )
        )


def test_write_lattice_beat_end_when_gate_open(tmp_path: Path) -> None:
    company = tmp_path / "acme"
    memory = EpisodicStore(company / "memory")
    _append_cluster(memory)

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / ".harness").mkdir()

    scheduler = Scheduler(company_root=company)
    scheduler._write_lattice_beat_end(
        employee=_employee(),
        run_id=uid("run_1"),
        working_dir=worktree,
    )

    path = worktree / ".harness" / "lattice-beat-end.json"
    assert path.is_file()
    payload = json.loads(path.read_text())
    assert payload["gate_open"] is True
    assert payload["employee_id"] == "bex"
    assert "gate open" in payload["teaser"].lower()


def test_no_teaser_file_when_gate_closed(tmp_path: Path) -> None:
    company = tmp_path / "acme"
    EpisodicStore(company / "memory")

    worktree = tmp_path / "worktree"
    worktree.mkdir()

    scheduler = Scheduler(company_root=company)
    scheduler._write_lattice_beat_end(
        employee=_employee(),
        run_id=uid("run_1"),
        working_dir=worktree,
    )

    assert not (worktree / ".harness" / "lattice-beat-end.json").exists()


def test_lattice_teaser_never_raises_on_bad_company_root(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    scheduler = Scheduler(company_root=tmp_path / "missing" / "structure")
    scheduler._write_lattice_beat_end(
        employee=_employee(),
        run_id=uid("run_1"),
        working_dir=worktree,
    )
