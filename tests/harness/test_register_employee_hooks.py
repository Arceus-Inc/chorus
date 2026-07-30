"""register_employee_hooks — forge on, STOP continue off by default (lean Bex)."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.roles._subagent import SubagentSpec
from chorus_harness._dream_hooks import (
    DangerousToolVetoHook,
    EvidenceContinueHook,
    EvidenceForgeVetoHook,
    register_employee_hooks,
)

pytestmark = pytest.mark.unit


class _HarnessStub:
    def __init__(self) -> None:
        self.hooks: list[object] = []

    def register_hook(self, hook: object) -> None:
        self.hooks.append(hook)


def _spec_with_evidence() -> SubagentSpec:
    return SubagentSpec(
        name="test_author",
        description="writes tests",
        tools=("read_file", "write_file"),
        evidence_path="test_plan.json",
        evidence_claim={"authored": True},
    )


def test_register_skips_evidence_continue_by_default(tmp_path: Path) -> None:
    harness = _HarnessStub()
    register_employee_hooks(
        harness, working_dir=tmp_path, subagents=(_spec_with_evidence(),)
    )
    assert any(isinstance(h, DangerousToolVetoHook) for h in harness.hooks)
    assert any(isinstance(h, EvidenceForgeVetoHook) for h in harness.hooks)
    assert not any(isinstance(h, EvidenceContinueHook) for h in harness.hooks)



def test_factory_stop_evidence_requirements_defaults_false() -> None:
    import inspect

    from chorus_harness._factory import EmployeeHarnessFactory

    sig = inspect.signature(EmployeeHarnessFactory.__init__)
    assert sig.parameters["stop_evidence_requirements"].default is False


def test_register_evidence_continue_when_opted_in(tmp_path: Path) -> None:
    harness = _HarnessStub()
    register_employee_hooks(
        harness,
        working_dir=tmp_path,
        subagents=(_spec_with_evidence(),),
        stop_evidence_requirements=True,
    )
    assert any(isinstance(h, EvidenceContinueHook) for h in harness.hooks)
