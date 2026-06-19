"""End-to-end: the keys-free §4 trust-presets suite runs and writes its report (spec 04 §4)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SUITE = Path(__file__).resolve().parents[2] / "examples" / "trust_presets_suite.py"


def test_trust_presets_suite_passes() -> None:
    spec = importlib.util.spec_from_file_location("trust_presets_suite", _SUITE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass annotation resolution needs the module registered
    spec.loader.exec_module(module)
    scenarios = module._scenarios()
    by_name = {s.name: s for s in scenarios}
    # standard is untouched; explicit low-trust is clamped; missing boundary + inline secret are denied.
    assert "unrestricted" in by_name["standard task"].after
    assert "read-only / plan" == by_name["explicit low_trust_review"].after
    assert by_name["low-trust, no boundary"].after.startswith("DENIED")
    assert by_name["low-trust, inline secret"].after.startswith("DENIED")
    assert module.main() == 0
