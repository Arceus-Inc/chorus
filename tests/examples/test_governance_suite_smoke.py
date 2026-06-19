"""End-to-end: the keys-free §5 governance suite runs and writes its report (spec 04 §5)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SUITE = Path(__file__).resolve().parents[2] / "examples" / "governance_suite.py"


def test_governance_suite_passes() -> None:
    spec = importlib.util.spec_from_file_location("governance_suite", _SUITE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass annotation resolution needs the module registered
    spec.loader.exec_module(module)
    scenarios = module._scenarios()
    # all four governed actions + the third decision (request_revision) are exercised.
    assert {s.action for s in scenarios} == {
        "hire_employee",
        "plan_approval",
        "board_approval",
        "task_gate",
    }
    assert "request_revision" in {s.decision for s in scenarios}
    assert module.main() == 0
