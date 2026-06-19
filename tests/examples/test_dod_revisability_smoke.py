"""End-to-end: the keys-free §1 DoD-revisability suite runs and writes its report (spec 04 §1)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SUITE = Path(__file__).resolve().parents[2] / "examples" / "dod_revisability_suite.py"


def test_dod_revisability_suite_passes() -> None:
    spec = importlib.util.spec_from_file_location("dod_revisability_suite", _SUITE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass annotation resolution needs the module registered
    spec.loader.exec_module(module)
    scenarios = module._scenarios()
    names = {s.name for s in scenarios}
    assert any("tighten" in n for n in names) and any("loosen" in n for n in names)
    # the headline guarantees: a tighten is applied; a denied loosen keeps the stricter DoD.
    tighten = next(s for s in scenarios if "tighten" in s.name)
    assert tighten.before != tighten.after  # raised the bar
    denied = next(s for s in scenarios if "denied" in s.name)
    assert denied.before == denied.after  # kept the stricter DoD
    assert module.main() == 0
