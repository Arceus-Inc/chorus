"""The dream beat adapter — RunTaskResult → BeatOutcome (spec 03 §3, spec 05 dream seam).

``to_beat_outcome`` is the verdict rule: a beat *passed* iff dream's plan fully completed (every
ledger step ``done``). ``DreamBeatRunner`` runs one beat through a dream Harness and lands that
verdict, turning any harness error into a clean ``passed=False`` rather than an unhandled crash.
The adapter never imports dream — it reads the result through narrow protocols, so these fakes stand
in for dream's real types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from chorus.adapters import DreamBeatRunner, ModelRate, TokenPricing, to_beat_outcome

pytestmark = pytest.mark.unit


# -- fakes shaped like dream's RunTaskResult (the read-only surface the adapter consumes) ----------


@dataclass(frozen=True)
class _Step:
    status: str


@dataclass(frozen=True)
class _Ledger:
    steps: tuple[_Step, ...]


@dataclass(frozen=True)
class _Sprint:
    outcome: str | None


@dataclass(frozen=True)
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@dataclass(frozen=True)
class _Result:
    final_ledger: _Ledger
    sprints: tuple[_Sprint, ...] = field(default_factory=tuple)
    usage_by_model: dict[str, _Usage] = field(default_factory=dict)


def _result(
    *statuses: str,
    sprints: tuple[str | None, ...] = (),
    usage_by_model: dict[str, _Usage] | None = None,
) -> _Result:
    return _Result(
        final_ledger=_Ledger(steps=tuple(_Step(s) for s in statuses)),
        sprints=tuple(_Sprint(o) for o in sprints),
        usage_by_model=usage_by_model or {},
    )


class _FakeHarness:
    """A stand-in dream Harness: returns a canned result, or raises a canned error."""

    def __init__(self, *, result: _Result | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[str] = []

    async def run_task(self, *, task_id: str, intent: str) -> _Result:
        self.calls.append(task_id)
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


# -- to_beat_outcome: the verdict rule -------------------------------------------------------------


def test_passed_when_every_step_done() -> None:
    outcome = to_beat_outcome(_result("done", "done", sprints=("pass", "pass")))
    assert outcome.passed is True
    assert outcome.outcome["steps_total"] == 2
    assert outcome.outcome["steps_done"] == 2
    assert outcome.outcome["sprint_outcomes"] == ["pass", "pass"]


def test_not_passed_when_a_step_is_unfinished() -> None:
    assert to_beat_outcome(_result("done", "in_progress")).passed is False


def test_not_passed_when_a_step_is_blocked() -> None:
    outcome = to_beat_outcome(_result("done", "blocked"))
    assert outcome.passed is False
    assert outcome.outcome["steps_blocked"] == 1


def test_empty_plan_is_not_passed() -> None:
    # no steps means nothing was actually completed — never a silent pass
    assert to_beat_outcome(_result()).passed is False


# -- cost: the beat's spend, priced from dream's metered usage -------------------------------------


def test_unpriced_beat_costs_zero() -> None:
    result = _result("done", usage_by_model={"gpt-x": _Usage(input_tokens=1_000_000)})
    assert to_beat_outcome(result).cost_cents == 0  # no pricing supplied


def test_priced_beat_carries_real_cost() -> None:
    pricing = TokenPricing(rates={"gpt-x": ModelRate(125, 1000)})
    result = _result(
        "done", usage_by_model={"gpt-x": _Usage(input_tokens=1_000_000, output_tokens=200_000)}
    )
    outcome = to_beat_outcome(result, pricing=pricing)
    assert outcome.cost_cents == 325  # 125 + 200
    assert outcome.outcome["cost_cents"] == 325


def test_priced_beat_with_no_usage_costs_zero() -> None:
    pricing = TokenPricing(rates={"gpt-x": ModelRate(125, 1000)})
    assert to_beat_outcome(_result("done"), pricing=pricing).cost_cents == 0


def test_outcome_carries_model_and_token_totals() -> None:
    result = _result("done", usage_by_model={"gpt-x": _Usage(input_tokens=100, output_tokens=40)})
    outcome = to_beat_outcome(result)  # tokens are surfaced regardless of pricing
    assert outcome.model == "gpt-x"
    assert outcome.input_tokens == 100
    assert outcome.output_tokens == 40


def test_multiple_models_are_joined_and_tokens_summed() -> None:
    result = _result(
        "done",
        usage_by_model={
            "gpt-4": _Usage(input_tokens=10, output_tokens=1),
            "gpt-5.2": _Usage(input_tokens=20, output_tokens=2),
        },
    )
    outcome = to_beat_outcome(result)
    assert outcome.model == "gpt-4+gpt-5.2"  # sorted, joined
    assert outcome.input_tokens == 30
    assert outcome.output_tokens == 3


# -- DreamBeatRunner: run one beat through the harness ---------------------------------------------


async def test_run_task_maps_a_completed_plan_to_passed() -> None:
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness)
    outcome = await runner.run_task(task_id="t1", intent="ship it")
    assert outcome.passed is True
    assert harness.calls == ["t1"]


async def test_run_task_turns_a_harness_error_into_a_failed_beat() -> None:
    runner = DreamBeatRunner(_FakeHarness(error=RuntimeError("provider 500")))
    outcome = await runner.run_task(task_id="t1", intent="ship it")
    assert outcome.passed is False
    assert "provider 500" in str(outcome.outcome["error"])


async def test_run_task_prices_the_beat_when_pricing_is_wired() -> None:
    harness = _FakeHarness(
        result=_result("done", usage_by_model={"gpt-x": _Usage(input_tokens=2_000_000)})
    )
    runner = DreamBeatRunner(harness, pricing=TokenPricing(rates={"gpt-x": ModelRate(125, 1000)}))
    outcome = await runner.run_task(task_id="t1", intent="ship it")
    assert outcome.cost_cents == 250  # 2 Mtok input * 125 c/Mtok


async def test_run_task_is_unpriced_without_pricing() -> None:
    harness = _FakeHarness(
        result=_result("done", usage_by_model={"gpt-x": _Usage(input_tokens=2_000_000)})
    )
    outcome = await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")
    assert outcome.cost_cents == 0


async def test_run_task_accepts_and_ignores_a_chorus_observer() -> None:
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness)
    seen: list[object] = []
    outcome = await runner.run_task(task_id="t1", intent="x", observer=seen.append)
    assert outcome.passed is True
    assert seen == []  # M1 does not forward chorus events into dream
