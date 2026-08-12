"""register_employee_hooks — forge on, STOP continue off by default (lean Bex)."""

from __future__ import annotations

from pathlib import Path

import pytest
from dream.contracts.hook import HookEvent
from dream.contracts.strategy import LandedPhase, RecoveryHint

from chorus.context import (
    BudgetPosition,
    Citation,
    ContextAudience,
    DoDRequirement,
    PriorBeat,
    TaskContextPacket,
    TaskContract,
)
from chorus.roles._subagent import SubagentSpec
from chorus_harness._dream_hooks import (
    BeatContextKind,
    BeatContextSection,
    DangerousToolVetoHook,
    EvidenceContinueHook,
    EvidenceForgeVetoHook,
    ShadowCheckpointHook,
    VolatileBeatPacket,
    VolatileBeatPacketHook,
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
    assert any(isinstance(h, ShadowCheckpointHook) for h in harness.hooks)
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


async def test_volatile_packet_injects_each_session_and_consumes_once(
    tmp_path: Path,
) -> None:
    consumed = 0

    def consume() -> None:
        nonlocal consumed
        consumed += 1

    packet = VolatileBeatPacket(
        sections=(
            BeatContextSection(
                kind=BeatContextKind.RUNTIME,
                content="## Inbox\nparser must handle CRLF",
            ),
        ),
        on_injected=consume,
    )
    harness = _HarnessStub()
    register_employee_hooks(
        harness,
        working_dir=tmp_path,
        volatile_packet=packet,
    )
    hook = next(h for h in harness.hooks if isinstance(h, VolatileBeatPacketHook))

    first = await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "generator", "prompt": "one"})
    second = await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "generator", "prompt": "two"})

    assert "parser must handle CRLF" in (first.inject_context or "")
    assert first.inject_context == second.inject_context
    assert consumed == 1


async def test_volatile_packet_keeps_evaluator_independent() -> None:
    packet = VolatileBeatPacket(
        sections=(),
        task_context=TaskContextPacket(
            task_id="task-1",
            contract=TaskContract(intent="ship", dod=(DoDRequirement("command", "pytest -q"),)),
            ancestry=(),
            prior_beats=(
                PriorBeat(
                    run_id="run-1",
                    phase=LandedPhase.NEEDS_REWORK,
                    recovery_hint=RecoveryHint.REWORK,
                    evaluator_notes=("fix the regression",),
                    citation=Citation("ledger.run_carryover:run-1", "landed beat carryover"),
                ),
            ),
            inbox=(),
            sibling_failures=(),
            budget=BudgetPosition(0, None, 1),
            citations=(),
        ),
    )
    hook = VolatileBeatPacketHook(packet)

    planner = await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "planner", "prompt": "plan"})
    generator = await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "generator", "prompt": "work"})
    evaluator = await hook(HookEvent.USER_PROMPT_SUBMIT, {"role": "evaluator", "prompt": "judge"})

    assert "fix the regression" in (planner.inject_context or "")
    assert "fix the regression" in (generator.inject_context or "")
    assert "fix the regression" not in (evaluator.inject_context or "")
    assert generator.inject_context == packet.render(ContextAudience.GENERATOR)


async def test_volatile_packet_fails_closed_without_dream_role() -> None:
    packet = VolatileBeatPacket(
        sections=(BeatContextSection(BeatContextKind.LATTICE, "private state"),),
    )

    outcome = await VolatileBeatPacketHook(packet)(
        HookEvent.USER_PROMPT_SUBMIT, {"prompt": "work"}
    )

    assert outcome.inject_context is None
