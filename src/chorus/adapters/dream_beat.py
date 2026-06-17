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
from contextlib import suppress
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

from chorus.adapters._failure import failure_outcome
from chorus.adapters._observer import DreamObserverBridge
from chorus.adapters._pricing import TokenPricing, UsageView
from chorus.events import Event
from chorus.heartbeat import BeatOutcome
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
        max_sprints: int | None = None,
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
        max_sprints: int | None = 1,
        timeout_s: float | None = 90.0,
        working_dir: str | Path | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._harness = harness
        self._pricing = pricing
        self._max_sprints = max_sprints
        self._timeout_s = timeout_s
        self._working_dir = Path(working_dir) if working_dir is not None else None
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
            DreamObserverBridge(observer, task_id=task_id, clock=self._clock)
            if observer is not None
            else None
        )
        # dream's verification step ``kind`` must be one of {test, lint, eval} (its SprintContract
        # rejects anything else and the whole beat errors before the generator). A chorus Command DoD
        # is a generic shell command, so it maps to ``eval``; the oracle runs ``command`` regardless of
        # the kind label.
        steps: tuple[dict[str, str], ...] = tuple(
            {"kind": "eval", "command": step.command} for step in verification
        )
        try:
            run = self._harness.run_task(
                task_id=task_id,
                intent=intent,
                verification_steps=steps,
                observer=bridge,
                max_sprints=self._max_sprints,
            )
            result = await asyncio.wait_for(run, timeout=self._timeout_s)
        except TimeoutError as exc:
            if verification and await self._verification_passed(verification):
                return BeatOutcome(
                    passed=True,
                    summary="objective verification passed after dream timeout",
                    outcome={
                        "steps_total": len(verification),
                        "steps_done": len(verification),
                        "verified_after_timeout": True,
                        "timeout_s": self._timeout_s,
                    },
                )
            return failure_outcome(exc)
        except asyncio.CancelledError:
            raise  # structured cancellation must propagate — never classify it as a beat outcome
        except Exception as exc:  # typed by failure_outcome — a beat never crashes the dispatch loop
            return failure_outcome(exc)
        return to_beat_outcome(result, pricing=self._pricing)

    async def _verification_passed(self, verification: tuple[VerificationStep, ...]) -> bool:
        if self._working_dir is None:
            return False
        for step in verification:
            try:
                process = await asyncio.create_subprocess_shell(
                    step.command,
                    cwd=self._working_dir,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    await asyncio.wait_for(process.communicate(), timeout=step.timeout_s)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        process.kill()
                        await process.wait()
                    return False
            except OSError:
                return False
            if process.returncode != 0:
                return False
        return True


__all__ = [
    "DreamBeatRunner",
    "DreamStepStatus",
    "RunResult",
    "TaskHarness",
    "UsageView",
    "to_beat_outcome",
]
