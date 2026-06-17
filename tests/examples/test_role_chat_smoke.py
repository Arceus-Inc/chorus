"""End-to-end: the keyed role-aware chat smoke runs green (spec 06 §2, spec 05).

Builds a role-aware chat harness for an ``engineer`` and runs one real ``run_task`` turn. Requires
Azure OpenAI credentials; the smoke itself skips (returns 0) when they are unset, so this test passes
in CI without keys and exercises the live engineer-writes-a-file path locally when they are present.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_SMOKE = Path(__file__).resolve().parents[2] / "examples" / "role_chat_smoke.py"


def test_role_chat_smoke_runs() -> None:
    spec = importlib.util.spec_from_file_location("role_chat_smoke", _SMOKE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.main() == 0
