"""RoleBeatRunner — the conversational, role-bound beat adapter (spec 05, spec 06 §2).

Like ``DreamBeatRunner`` but over dream's ``run_role`` (a conversational turn as a role) instead of
``run_task`` (the autonomous sprint loop). It is dream-free: it talks to a :class:`RoleHarness`
Protocol, so these drive it with a fake harness — proving the result→``BeatOutcome`` mapping, the
pricing, and the four-way failure contract without any provider.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from chorus.adapters import RoleBeatConfig, RoleBeatRunner, RoleRunOutcome
from chorus.adapters._pricing import ModelRate, TokenPricing
from chorus.events import Event
from chorus.heartbeat import BeatDisposition

pytestmark = pytest.mark.unit

_CONFIG = RoleBeatConfig(system_prompt="You are an engineer.", tools=("read_file",))


class _FakeHarness:
    """A stand-in :class:`RoleHarness` that returns a canned outcome and records the call."""

    def __init__(self, outcome: RoleRunOutcome | None = None, *, raises: BaseException | None = None) -> None:
        self._outcome = outcome or RoleRunOutcome(
            final_text="done", model="gpt-x", input_tokens=1000, output_tokens=500
        )
        self._raises = raises
        self.calls: list[tuple[RoleBeatConfig, str]] = []

    async def run_role(
        self, config: RoleBeatConfig, intent: str, *, observer: Callable[[Event], None] | None = None
    ) -> RoleRunOutcome:
        self.calls.append((config, intent))
        if self._raises is not None:
            raise self._raises
        return self._outcome


def _run(runner: RoleBeatRunner, intent: str = "hello") -> object:
    return asyncio.run(runner.run_task(task_id="t1", intent=intent))


def test_runs_the_role_and_maps_the_reply_to_a_passed_outcome() -> None:
    harness = _FakeHarness()
    runner = RoleBeatRunner(harness, _CONFIG)
    outcome = _run(runner, "write hello")
    assert harness.calls == [(_CONFIG, "write hello")]  # the role config + intent reach run_role
    assert outcome.passed is True  # type: ignore[attr-defined]
    assert outcome.disposition is BeatDisposition.PASSED  # type: ignore[attr-defined]
    assert outcome.outcome["final_text"] == "done"  # type: ignore[attr-defined]


def test_prices_the_turn_from_its_usage() -> None:
    harness = _FakeHarness(
        RoleRunOutcome(final_text="ok", model="gpt-x", input_tokens=1_000_000, output_tokens=0)
    )
    pricing = TokenPricing(rates={}, default=ModelRate(125, 1000))  # 125c / Mtok input
    runner = RoleBeatRunner(harness, _CONFIG, pricing=pricing)
    outcome = _run(runner)
    assert outcome.cost_cents == 125  # type: ignore[attr-defined]
    assert outcome.model == "gpt-x"  # type: ignore[attr-defined]


def test_unpriced_runner_costs_zero() -> None:
    outcome = _run(RoleBeatRunner(_FakeHarness(), _CONFIG))
    assert outcome.cost_cents == 0  # type: ignore[attr-defined]


def test_an_engine_fault_is_errored_never_crashes() -> None:
    harness = _FakeHarness(raises=RuntimeError("provider exploded"))
    outcome = _run(RoleBeatRunner(harness, _CONFIG))
    assert outcome.passed is False  # type: ignore[attr-defined]
    assert outcome.disposition is BeatDisposition.ERRORED  # type: ignore[attr-defined]


def test_a_dream_cancel_is_cancelled() -> None:
    boom = RuntimeError("stopped")
    boom.code = "dream.cancelled"  # type: ignore[attr-defined]  # dream's stable cancel contract
    outcome = _run(RoleBeatRunner(_FakeHarness(raises=boom), _CONFIG))
    assert outcome.disposition is BeatDisposition.CANCELLED  # type: ignore[attr-defined]


def test_asyncio_cancellation_propagates() -> None:
    harness = _FakeHarness(raises=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        _run(RoleBeatRunner(harness, _CONFIG))
