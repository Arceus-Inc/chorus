"""LanderRegistry — the outcome-landing seam (spec 04 §2, spec 09 §4).

Each role's ``outcome_kind`` maps to an :class:`OutcomeLander`; the kernel dispatches a passed beat's
landing through this registry, so adding an employee that lands a new kind of artifact is a plugin, not
a kernel edit.
"""

from __future__ import annotations

from typing import Any

import pytest

from chorus.outcomes import Artifact, ArtifactType, LanderRegistry

pytestmark = pytest.mark.unit


class _FakeLander:
    """An :class:`OutcomeLander` stand-in keyed by its outcome_kind."""

    def __init__(self, outcome_kind: str) -> None:
        self.outcome_kind = outcome_kind

    async def land(self, task: Any, result: Any) -> Artifact:
        return Artifact(task_id="t", type=ArtifactType.PR)


def test_register_then_get_by_outcome_kind() -> None:
    registry = LanderRegistry()
    lander = _FakeLander("pr")
    registry.register(lander)
    assert registry.get("pr") is lander
    assert "pr" in registry


def test_get_unknown_kind_returns_none() -> None:
    registry = LanderRegistry()
    assert registry.get("verdict") is None
    assert "verdict" not in registry


def test_from_landers_builds_a_registry() -> None:
    registry = LanderRegistry.from_landers([_FakeLander("pr"), _FakeLander("verdict")])
    assert registry.get("pr") is not None
    assert registry.get("verdict") is not None
