"""RoleBeatRunner — a conversational, role-bound beat over dream's ``run_role`` (spec 05, spec 06 §2).

The sibling of :class:`DreamBeatRunner`: where that runs ``run_task`` (the autonomous
planner→sprint→evaluator loop, DoD-verified), this runs ``run_role`` — one conversational turn *as a
role*, applying the role's system prompt, tool allow-list, and permission posture. It is the seam the
``chat`` path uses so an employee actually behaves like its role.

Dream-free by the same discipline as ``DreamBeatRunner``: it talks to a :class:`RoleHarness` Protocol
(the concrete dream ``run_role`` wrapper lives at the composition root) and takes a
:class:`~chorus.roles.RoleBeatConfig` (the dream-free projection of the role). The four-way failure
contract (spec 05 §5) is shared via :func:`chorus.adapters._failure.failure_outcome`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from chorus.adapters._failure import failure_outcome
from chorus.adapters._pricing import TokenPricing
from chorus.events import Event
from chorus.heartbeat import BeatOutcome
from chorus.outcomes import VerificationStep
from chorus.roles import RoleBeatConfig

_SUMMARY_CHARS = 80


@dataclass(frozen=True)
class RoleRunOutcome:
    """The chorus projection of dream's ``run_role`` result — built by the composition root.

    Carries the reply text + the turn's token usage. The token fields match the :class:`UsageView`
    shape, so a :class:`TokenPricing` prices the outcome directly. dream-free: the seam converts
    dream's ``RunRoleResult`` into this.
    """

    final_text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


@runtime_checkable
class RoleHarness(Protocol):
    """Runs one conversational beat as a role — dream's ``run_role`` at the seam (spec 06 §2)."""

    async def run_role(
        self,
        config: RoleBeatConfig,
        intent: str,
        *,
        observer: Callable[[Event], None] | None = None,
    ) -> RoleRunOutcome: ...


class RoleBeatRunner:
    """Run a beat as a role through a :class:`RoleHarness`, landing it as a :class:`BeatOutcome`.

    Satisfies the :class:`~chorus.heartbeat.BeatRunner` protocol, so the scheduler/chat drive it like
    any other beat runner. Constructed *per role* (the chat resolves the employee's role up front), so
    ``run_task``'s ``verification`` is unused here — a chat turn is a conversation, not a DoD-verified
    task (DoD verification stays on the autonomous ``run_task`` path).
    """

    def __init__(
        self, harness: RoleHarness, config: RoleBeatConfig, *, pricing: TokenPricing | None = None
    ) -> None:
        self._harness = harness
        self._config = config
        self._pricing = pricing

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        observer: Callable[[Event], None] | None = None,
    ) -> BeatOutcome:
        del task_id, verification  # conversational turn: the role config carries the role, not a DoD
        try:
            result = await self._harness.run_role(self._config, intent, observer=observer)
        except asyncio.CancelledError:
            raise  # structured cancellation must propagate — never a beat outcome
        except Exception as exc:  # typed by failure_outcome — a beat never crashes the dispatch loop
            return failure_outcome(exc)
        cost = self._pricing.cost_cents({result.model: result}) if self._pricing is not None else 0
        return BeatOutcome(
            passed=True,
            outcome={"final_text": result.final_text},
            summary=_summary(result.final_text),
            cost_cents=cost,
            model=result.model,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


def _summary(text: str) -> str:
    """A one-line, length-capped gloss of the reply for the verdict footer."""
    flat = " ".join(text.split())
    return flat if len(flat) <= _SUMMARY_CHARS else flat[: _SUMMARY_CHARS - 1] + "…"


__all__ = ["RoleBeatRunner", "RoleHarness", "RoleRunOutcome"]
