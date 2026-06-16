"""The dream beat adapter — run a beat through a dream Harness (spec 03 §3, spec 05 dream seam).

A concrete :class:`~chorus.heartbeat.BeatRunner`: one ``harness.run_task`` call, its result mapped to
the chorus :class:`~chorus.heartbeat.BeatOutcome` the beat lands. The verdict rule is **passed iff the
plan fully completed** — every step in dream's final ledger is ``done``.

This module deliberately does **not** import dream. It depends only on the narrow read-only shape of
dream's ``RunTaskResult`` (the protocols below), so the SDK import stays at the composition root
(``examples/real_beat.py`` / Arceus) and the adapter is a pure, fully testable unit.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol

from chorus.adapters._pricing import TokenPricing, UsageView
from chorus.events import Event, EventKind
from chorus.heartbeat import BeatDisposition, BeatOutcome
from chorus.outcomes import VerificationStep


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DreamStepStatus(StrEnum):
    """The dream planner step statuses a beat's verdict reads (mirrors dream ``planner.StepStatus``)."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    BLOCKED = "blocked"


class RunStep(Protocol):
    """One planned step — the adapter reads only its status."""

    @property
    def status(self) -> str: ...


class RunLedger(Protocol):
    """The final plan ledger — the adapter reads only its steps."""

    @property
    def steps(self) -> Sequence[RunStep]: ...


class RunSprint(Protocol):
    """One sprint's recorded evaluation outcome (``pass`` / ``needs-changes`` / ``fail`` / unset)."""

    @property
    def outcome(self) -> str | None: ...


class RunResult(Protocol):
    """The minimal read-only surface of dream's ``RunTaskResult`` the adapter depends on."""

    @property
    def final_ledger(self) -> RunLedger: ...

    @property
    def sprints(self) -> Sequence[RunSprint]: ...

    @property
    def usage_by_model(self) -> Mapping[str, UsageView]:
        """Per-model token usage dream metered for the run (empty on older dream pins → cost 0)."""
        ...


class _DreamObserver(Protocol):
    """dream's ``RunTaskObserver`` shape — a sink for the engine's dict event stream (spec 05 §4)."""

    def on_event(self, event: dict[str, Any]) -> None: ...


class TaskHarness(Protocol):
    """A built dream Harness — the one call a beat makes (the adapter's sole dependency)."""

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification_steps: tuple[dict[str, str], ...] = (),
        observer: _DreamObserver | None = None,
    ) -> RunResult: ...


# dream's run_task observer emits plain dicts with a stable ``"kind"``; chorus witnesses the liveness
# subset that maps 1:1 onto its closed ``run.*`` vocabulary (spec 08 §2). Macro lifecycle kinds
# (planner/generator/sprint/contract/negotiation) have no chorus run.* equivalent yet and are skipped
# rather than mislabelled — the witnessed micro-stream is the liveness signal spec 05 §4 needs.
_DREAM_TO_CHORUS_KIND: dict[str, EventKind] = {
    "task.started": EventKind.RUN_STARTED,
    "task.completed": EventKind.RUN_DONE,
    "role.text": EventKind.RUN_TEXT,
    "role.tool.start": EventKind.RUN_TOOL_USE,
    "role.tool.result": EventKind.RUN_TOOL_RESULT,
    "evaluator.completed": EventKind.RUN_EVALUATED,
}


class _ObserverBridge:
    """Translate dream's dict event stream into chorus :class:`Event` envelopes (spec 05 §4).

    chorus passes ``event_bus.emit`` (a ``Callable[[Event], None]``); dream calls ``on_event(dict)``.
    This bridge sits between them: each dream event with a chorus ``run.*`` equivalent becomes a typed
    :class:`Event` carrying the original ``kind`` + payload, so chorus witnesses dream's stream
    instead of parsing prose. Unmapped kinds are dropped (the closed vocabulary stays closed).
    """

    def __init__(
        self, emit: Callable[[Event], None], *, task_id: str, clock: Callable[[], datetime]
    ) -> None:
        self._emit = emit
        self._task_id = task_id
        self._clock = clock

    def on_event(self, event: dict[str, Any]) -> None:
        kind = _DREAM_TO_CHORUS_KIND.get(str(event.get("kind", "")))
        if kind is None:
            return
        payload: dict[str, Any] = {k: v for k, v in event.items() if k != "kind"}
        payload["dream_kind"] = event.get("kind")
        self._emit(Event(kind=kind, at=self._clock(), task_id=self._task_id, payload=payload))


def _failure_outcome(exc: BaseException) -> BeatOutcome:
    """Classify a raise out of ``run_task`` into a typed disposition (spec 05 §5).

    A ``dream.TaskCancelled`` (stable ``code == "dream.cancelled"``) is a cooperative cancel; anything
    else — a ``dream.RunTaskError`` carrying a typed ``phase``, or any unexpected fault — is an engine
    error. The adapter reads dream's error contract structurally (``code``/``phase``), never importing
    dream, so it stays a pure unit. ``asyncio.CancelledError`` is re-raised by the caller, never here.
    """
    if getattr(exc, "code", None) == "dream.cancelled":
        return BeatOutcome(
            passed=False,
            disposition=BeatDisposition.CANCELLED,
            outcome={"cancelled": repr(exc)},
            summary=f"beat cancelled: {exc}",
        )
    phase = getattr(exc, "phase", None)
    return BeatOutcome(
        passed=False,
        disposition=BeatDisposition.ERRORED,
        outcome={"error": repr(exc), "phase": phase},
        summary=f"beat errored: {exc}",
    )


def to_beat_outcome(result: RunResult, *, pricing: TokenPricing | None = None) -> BeatOutcome:
    """Map a dream run result to the chorus verdict: ``passed`` iff every plan step is ``done``.

    An empty plan is never a silent pass. ``outcome`` carries the step tally and the per-sprint
    evaluation outcomes for the audit/DoD record; ``summary`` is a one-line human gloss. When
    ``pricing`` is supplied the beat's spend is priced from dream's metered usage and lands on
    :attr:`BeatOutcome.cost_cents` for the budget gates; without it the beat is unpriced (cost 0).
    """
    steps = list(result.final_ledger.steps)
    done = sum(1 for step in steps if step.status == DreamStepStatus.DONE)
    blocked = sum(1 for step in steps if step.status == DreamStepStatus.BLOCKED)
    passed = len(steps) > 0 and done == len(steps)
    usage = result.usage_by_model
    cost_cents = pricing.cost_cents(usage) if pricing is not None else 0
    model = "+".join(sorted(usage))  # "" / "gpt-5.2" / "gpt-4+gpt-5.2"
    input_tokens = sum(u.input_tokens for u in usage.values())
    output_tokens = sum(u.output_tokens for u in usage.values())
    outcome: dict[str, object] = {
        "steps_total": len(steps),
        "steps_done": done,
        "steps_blocked": blocked,
        "sprint_outcomes": [sprint.outcome for sprint in result.sprints],
        "cost_cents": cost_cents,
    }
    summary = (
        f"plan complete: {done}/{len(steps)} steps done"
        if passed
        else f"plan incomplete: {done}/{len(steps)} done, {blocked} blocked"
    )
    return BeatOutcome(
        passed=passed,
        outcome=outcome,
        summary=summary,
        cost_cents=cost_cents,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class DreamBeatRunner:
    """Run a beat through a dream Harness and land its result as a :class:`BeatOutcome` (spec 03 §3).

    The four-way failure contract (spec 05 §5) is enforced here: a clean return is priced and mapped
    by :func:`to_beat_outcome`; a ``dream.TaskCancelled`` becomes a ``CANCELLED`` disposition and a
    ``dream.RunTaskError`` (or any other fault) an ``ERRORED`` one — a raise is never swallowed into a
    silent pass. ``asyncio.CancelledError`` propagates so structured cancellation unwinds cleanly.
    When a chorus ``observer`` is supplied it is bridged into dream so chorus witnesses the run's
    structured event stream (spec 05 §4).
    """

    def __init__(
        self,
        harness: TaskHarness,
        *,
        pricing: TokenPricing | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._harness = harness
        self._pricing = pricing
        self._clock = clock or _utc_now

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        observer: Callable[[Event], None] | None = None,
    ) -> BeatOutcome:
        # Bridge the chorus observer into dream so the run's structured events reach the event log
        # (spec 05 §4); without one, dream runs silent (no bridge allocated).
        bridge = (
            _ObserverBridge(observer, task_id=task_id, clock=self._clock)
            if observer is not None
            else None
        )
        steps: tuple[dict[str, str], ...] = tuple(
            {"kind": "command", "command": step.command} for step in verification
        )
        try:
            result = await self._harness.run_task(
                task_id=task_id, intent=intent, verification_steps=steps, observer=bridge
            )
        except asyncio.CancelledError:
            raise  # structured cancellation must propagate — never classify it as a beat outcome
        except Exception as exc:  # typed by _failure_outcome — a beat never crashes the dispatch loop
            return _failure_outcome(exc)
        return to_beat_outcome(result, pricing=self._pricing)


__all__ = [
    "DreamBeatRunner",
    "DreamStepStatus",
    "RunResult",
    "TaskHarness",
    "UsageView",
    "to_beat_outcome",
]
