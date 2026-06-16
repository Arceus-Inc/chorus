"""End-to-end: the keys-free governance smoke runs and its gates resolve correctly (spec 04 §5)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SMOKE = Path(__file__).resolve().parents[2] / "examples" / "governance_smoke.py"


def test_governance_smoke_passes() -> None:
    spec = importlib.util.spec_from_file_location("governance_smoke", _SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
