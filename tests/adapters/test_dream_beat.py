"""The dream beat adapter — RunTaskResult → BeatOutcome (spec 03 §3, spec 05 dream seam).

``to_beat_outcome`` is the verdict rule: a beat *passed* iff dream's plan fully completed (every
ledger step ``done``). ``DreamBeatRunner`` runs one beat through a dream Harness and lands that
verdict, turning any harness error into a clean ``passed=False`` rather than an unhandled crash.
The adapter never imports dream — it reads the result through narrow protocols, so these fakes stand
in for dream's real types.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from chorus.adapters import DreamBeatRunner, ModelRate, TokenPricing, to_beat_outcome
from chorus.events import Event, EventKind
from chorus.heartbeat import BeatDisposition
from chorus.outcomes import VerificationStep

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


class _FakeRunTaskError(Exception):
    """Shaped like ``dream.RunTaskError``: a stable ``code`` and a typed ``phase``."""

    code = "dream.run_task"

    def __init__(self, message: str, *, phase: str) -> None:
        super().__init__(message)
        self.phase = phase


class _FakeTaskCancelled(Exception):
    """Shaped like ``dream.TaskCancelled``: the stable cooperative-cancel ``code``."""

    code = "dream.cancelled"


class _FakeHarness:
    """A stand-in dream Harness: returns a canned result, or raises a canned error.

    When ``events`` is given it replays them through the ``observer`` dream is handed, so the bridge's
    dream-dict -> chorus-Event translation can be exercised without a real engine.
    """

    def __init__(
        self,
        *,
        result: _Result | None = None,
        error: BaseException | None = None,
        events: tuple[dict[str, Any], ...] = (),
    ) -> None:
        self._result = result
        self._error = error
        self._events = events
        self.calls: list[str] = []
        self.verification_steps: tuple[dict[str, str], ...] = ()
        self.observer: object = None

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification_steps: tuple[dict[str, str], ...] = (),
        observer: object = None,
    ) -> _Result:
        self.calls.append(task_id)
        self.verification_steps = verification_steps
        self.observer = observer
        if observer is not None:
            for event in self._events:
                observer.on_event(event)  # type: ignore[attr-defined]
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
    assert outcome.disposition is BeatDisposition.ERRORED  # an unexpected fault is an engine error
    assert "provider 500" in str(outcome.outcome["error"])
    assert outcome.outcome["phase"] is None  # a non-dream error carries no phase


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


async def test_run_task_forwards_the_command_dod_as_verification_steps() -> None:
    harness = _FakeHarness(result=_result("done"))
    runner = DreamBeatRunner(harness)
    await runner.run_task(
        task_id="t1", intent="ship", verification=(VerificationStep(command="pytest -q"),)
    )
    # dream requires kind ∈ {test, lint, eval}; a chorus Command DoD maps to "eval"
    assert harness.verification_steps == ({"kind": "eval", "command": "pytest -q"},)


async def test_run_task_with_no_verification_passes_none() -> None:
    harness = _FakeHarness(result=_result("done"))
    await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")
    assert harness.verification_steps == ()


async def test_run_task_forwards_dream_events_to_the_observer() -> None:
    # dream replays its dict event stream through the bridge; chorus witnesses the mapped run.* subset.
    harness = _FakeHarness(
        result=_result("done"),
        events=(
            {"kind": "task.started", "task_id": "t1", "intent": "x"},
            {"kind": "role.text", "role": "generator", "text": "hello"},
            {"kind": "role.tool.start", "role": "generator", "tool": "bash"},
            {"kind": "evaluator.completed", "sprint_number": 1, "outcome": "pass", "score": 1.0},
            {"kind": "task.completed", "task_id": "t1", "sprint_count": 1},
        ),
    )
    seen: list[Event] = []
    outcome = await DreamBeatRunner(harness).run_task(task_id="t1", intent="x", observer=seen.append)
    assert outcome.passed is True
    assert [e.kind for e in seen] == [
        EventKind.RUN_STARTED,
        EventKind.RUN_TEXT,
        EventKind.RUN_TOOL_USE,
        EventKind.RUN_EVALUATED,
        EventKind.RUN_DONE,
    ]
    text = next(e for e in seen if e.kind is EventKind.RUN_TEXT)
    assert text.task_id == "t1"
    assert text.payload["text"] == "hello"
    assert text.payload["dream_kind"] == "role.text"  # the original dream kind is preserved


async def test_run_task_drops_dream_events_without_a_chorus_equivalent() -> None:
    # macro lifecycle kinds have no closed-vocabulary run.* equivalent yet — dropped, not mislabelled.
    harness = _FakeHarness(
        result=_result("done"),
        events=(
            {"kind": "planner.started", "task_id": "t1"},
            {"kind": "contract.written", "sprint_number": 1, "path": "c.json"},
            {"kind": "role.text", "text": "kept"},
        ),
    )
    seen: list[Event] = []
    await DreamBeatRunner(harness).run_task(task_id="t1", intent="x", observer=seen.append)
    assert [e.kind for e in seen] == [EventKind.RUN_TEXT]


async def test_run_task_runs_dream_silent_without_an_observer() -> None:
    harness = _FakeHarness(result=_result("done"), events=({"kind": "role.text", "text": "x"},))
    await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")
    assert harness.observer is None  # no observer in -> no bridge handed to dream


# -- the failure contract: a raise -> a typed disposition (spec 05 §5) -----------------------------


async def test_run_task_classifies_a_run_task_error_as_errored() -> None:
    harness = _FakeHarness(error=_FakeRunTaskError("planner blew up", phase="plan"))
    outcome = await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")
    assert outcome.passed is False
    assert outcome.disposition is BeatDisposition.ERRORED
    assert outcome.outcome["phase"] == "plan"  # the typed phase rides onto the outcome
    assert "planner blew up" in str(outcome.outcome["error"])


async def test_run_task_classifies_task_cancelled_as_cancelled() -> None:
    harness = _FakeHarness(error=_FakeTaskCancelled("budget exhausted"))
    outcome = await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")
    assert outcome.passed is False
    assert outcome.disposition is BeatDisposition.CANCELLED
    assert "budget exhausted" in str(outcome.outcome["cancelled"])


async def test_run_task_propagates_asyncio_cancellation() -> None:
    # structured cancellation must never be swallowed into a beat outcome — it re-raises.
    harness = _FakeHarness(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        await DreamBeatRunner(harness).run_task(task_id="t1", intent="x")


def test_beat_outcome_disposition_defaults_from_passed() -> None:
    from chorus.heartbeat import BeatOutcome

    assert BeatOutcome(passed=True).disposition is BeatDisposition.PASSED
    assert BeatOutcome(passed=False).disposition is BeatDisposition.DOD_FAILED
    assert to_beat_outcome(_result("done")).disposition is BeatDisposition.PASSED
    assert to_beat_outcome(_result("blocked")).disposition is BeatDisposition.DOD_FAILED
