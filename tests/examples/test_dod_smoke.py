"""End-to-end: the keys-free DoD smoke runs and its hook + ladder behave (spec 04 §1)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SMOKE = Path(__file__).resolve().parents[2] / "examples" / "dod_smoke.py"


def test_dod_smoke_passes() -> None:
    spec = importlib.util.spec_from_file_location("dod_smoke", _SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
