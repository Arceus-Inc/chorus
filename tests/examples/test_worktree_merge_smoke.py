"""End-to-end: the keyed worktree-isolation + merge smoke runs green (spec 04 §4, spec 06 §2).

Seeds a company from a real repo, runs one live ``run_task`` turn where a ``backend_engineer`` edits the
seeded code in its branch-isolated worktree, then merges that branch into company ``main``. Requires
Azure OpenAI credentials; the smoke skips (returns 0) when they are unset, so this passes in CI without
keys and exercises the full seed → isolate → merge loop locally when they are present.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SMOKE = Path(__file__).resolve().parents[2] / "examples" / "worktree_merge_smoke.py"


def test_worktree_merge_smoke_runs() -> None:
    spec = importlib.util.spec_from_file_location("worktree_merge_smoke", _SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
