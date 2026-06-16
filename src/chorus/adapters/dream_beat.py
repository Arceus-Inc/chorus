"""The dream beat adapter — run a beat through a dream Harness (spec 03 §3, spec 05 dream seam).

A concrete :class:`~chorus.heartbeat.BeatRunner`: one ``harness.run_task`` call, its result mapped to
the chorus :class:`~chorus.heartbeat.BeatOutcome` the beat lands. The verdict rule is **passed iff the
plan fully completed** — every step in dream's final ledger is ``done``.

This module deliberately does **not** import dream. It depends only on the narrow read-only shape of
dream's ``RunTaskResult`` (the protocols below), so the SDK import stays at the composition root
(``examples/real_beat.py`` / Arceus) and the adapter is a pure, fully testable unit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import StrEnum
from typing import Protocol

from chorus.adapters._pricing import TokenPricing, UsageView
from chorus.events import Event
from chorus.heartbeat import BeatOutcome
from chorus.outcomes import VerificationStep


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


class TaskHarness(Protocol):
    """A built dream Harness — the one call a beat makes (the adapter's sole dependency)."""

    async def run_task(
        self, *, task_id: str, intent: str, verification_steps: tuple[dict[str, str], ...] = ()
    ) -> RunResult: ...


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

    Any harness failure (provider error, tool crash, timeout) is caught and returned as a
    ``passed=False`` outcome, so a failed beat cleanly blocks its task and releases the lock rather
    than crashing the dispatched background task.
    """

    def __init__(self, harness: TaskHarness, *, pricing: TokenPricing | None = None) -> None:
        self._harness = harness
        self._pricing = pricing

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        observer: Callable[[Event], None] | None = None,
    ) -> BeatOutcome:
        # M1: the chorus event observer is not forwarded into dream (the event-stream bridge is a
        # later slice); chorus's own lifecycle events still fire from the scheduler and ledger.
        del observer
        steps: tuple[dict[str, str], ...] = tuple(
            {"kind": "command", "command": step.command} for step in verification
        )
        try:
            result = await self._harness.run_task(
                task_id=task_id, intent=intent, verification_steps=steps
            )
        except Exception as exc:  # broad on purpose — a beat must never crash the dispatch loop
            return BeatOutcome(
                passed=False,
                outcome={"error": repr(exc)},
                summary=f"beat errored: {exc}",
            )
        return to_beat_outcome(result, pricing=self._pricing)


__all__ = [
    "DreamBeatRunner",
    "DreamStepStatus",
    "RunResult",
    "TaskHarness",
    "UsageView",
    "to_beat_outcome",
]
