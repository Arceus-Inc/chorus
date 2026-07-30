"""Hard10 suite must observe the agent worktree, not the seed repo mirror.

First principle: Isolation.WORKTREE tools write to harness working_dir;
``company_root/repo`` is the merge/seed surface. Ship checks that look at
repo/ under-report deliverables and lie about quality.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
sys.path.insert(0, str(EXAMPLES))

from backend_engineer_hard10_suite import (  # noqa: E402
    _agent_deliverable_root,
    _shipped,
)
from bex_hard10_catalog import HardTicket  # noqa: E402

pytestmark = pytest.mark.unit


def _ticket() -> HardTicket:
    return HardTicket(
        id="t-obs",
        title="observation",
        skills=(),
        seed_readme="# stub\n",
        intent="x",
        rubric="y",
        ship_files=("queue.py", "migrate.py"),
        ship_hints=(("queue.py", "enqueue"),),
    )


def test_agent_deliverable_root_is_working_dir(tmp_path: Path) -> None:
    wt = tmp_path / "employee-worktree"
    wt.mkdir()
    assert _agent_deliverable_root(wt) == wt


def test_shipped_on_seed_repo_misses_worktree_files(tmp_path: Path) -> None:
    """RED proof of the old bug: seed repo looks empty while worktree has code."""
    seed = tmp_path / "repo"
    wt = tmp_path / "worktree"
    seed.mkdir()
    wt.mkdir()
    (seed / "README.md").write_text("# stub\n", encoding="utf-8")
    (wt / "queue.py").write_text("def enqueue():\n    pass\n", encoding="utf-8")
    (wt / "migrate.py").write_text("def upgrade():\n    pass\n", encoding="utf-8")

    ticket = _ticket()
    seed_map = _shipped(seed, ticket)
    wt_map = _shipped(_agent_deliverable_root(wt), ticket)

    assert seed_map["queue.py"] is False
    assert seed_map["migrate.py"] is False
    assert wt_map["queue.py"] is True
    assert wt_map["migrate.py"] is True
    assert wt_map["hint:queue.py:enqueue"] is True
