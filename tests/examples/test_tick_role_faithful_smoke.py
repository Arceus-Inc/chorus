"""End-to-end: the kernel ``tick`` dispatches a role-faithful beat (spec 06 §2).

Runs the converged tick path — hire an engineer, assign a task, ``run_tick`` — through the CLI's own
``build_beat_service``. Requires Azure credentials; the smoke skips (returns 0) when they are unset, so
this passes in CI without keys and exercises the live role-faithful tick locally when present.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SMOKE = Path(__file__).resolve().parents[2] / "examples" / "tick_role_faithful_smoke.py"


def test_tick_role_faithful_smoke_runs() -> None:
    spec = importlib.util.spec_from_file_location("tick_role_faithful_smoke", _SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
