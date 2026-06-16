"""The dream seam for a beat (spec 03 §3, spec 09 §4).

A beat's one external call is ``dream.run_task`` — the planner→sprint→evaluator loop. chorus binds to
it through :class:`BeatRunner` (a typed Protocol, not dream's concrete harness) so the scheduler is
testable with a fake and the real dream adapter stays at the composition root (spec 10 §1).
:class:`BeatOutcome` is the chorus-side projection of dream's ``RunTaskResult`` — only what the beat
needs to land a verdict: did the DoD pass, the structured outcome, and a short summary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from chorus.events import Event


@dataclass(frozen=True)
class BeatOutcome:
    """A beat's landed verdict — the chorus projection of dream's ``RunTaskResult`` (spec 05)."""

    passed: bool
    outcome: dict[str, object] = field(default_factory=dict)
    summary: str = ""
    # The beat's spend + the usage it was priced from — recorded as a cost_event (spec 04 §3).
    # ``model`` is the model(s) the beat used (``"a+b"`` when more than one); tokens are run totals.
    cost_cents: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class BeatRunner(Protocol):
    """The one dream call a beat makes (spec 03 §3) — the swappable execution seam (spec 09 §4)."""

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        observer: Callable[[Event], None] | None = None,
    ) -> BeatOutcome:
        """Run the task end-to-end; ``observer`` witnesses dream's structured run events."""
        ...


__all__ = [
    "BeatOutcome",
    "BeatRunner",
]
