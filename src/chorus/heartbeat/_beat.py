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
from enum import StrEnum
from typing import Protocol, runtime_checkable

from chorus.events import Event
from chorus.outcomes import VerificationStep


class BeatDisposition(StrEnum):
    """How a beat resolved — the four-way error contract chorus maps to a task state (spec 05 §5).

    ``PASSED``/``DOD_FAILED`` are clean returns (the evaluator accepted / ran-but-rejected); a raise
    out of ``run_task`` resolves to ``ERRORED`` (engine/tool fault → stranded → recovery ladder) or
    ``CANCELLED`` (cooperative cancel → task returns to its pre-beat state). A raise is **never**
    swallowed into ``done`` — the disposition keeps the engine fault distinct from a DoD failure.
    """

    PASSED = "passed"
    DOD_FAILED = "dod_failed"
    ERRORED = "errored"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BeatOutcome:
    """A beat's landed verdict — the chorus projection of dream's ``RunTaskResult`` (spec 05)."""

    passed: bool
    outcome: dict[str, object] = field(default_factory=dict)
    summary: str = ""
    # The entire raw agent record of the run — dream's event stream as JSON lines. Becomes the
    # episodic record's prose body (spec 07 §3): kept whole, mined later, trusted never.
    raw_record: str = ""
    # The beat's spend + the usage it was priced from — recorded as a cost_event (spec 04 §3).
    # ``model`` is the model(s) the beat used (``"a+b"`` when more than one); tokens are run totals.
    cost_cents: int = 0
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    # How the beat resolved (spec 05 §5). Defaults from ``passed`` for a clean return, so existing
    # callers need not set it; the dream adapter sets ``ERRORED``/``CANCELLED`` on a raise.
    disposition: BeatDisposition | None = None
    # An ERRORED beat whose fault is *transient* (e.g. a planner/evaluator parse blip — the model
    # emitted unparseable structured output). The scheduler re-runs a retryable beat before stranding
    # it; a clean return or a hard engine fault is never retryable.
    retryable: bool = False
    # Dream's typed EvaluationRecord is projected here by the adapter; Chorus never parses evaluator
    # JSON files.
    evaluator_notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.disposition is None:
            object.__setattr__(
                self,
                "disposition",
                BeatDisposition.PASSED if self.passed else BeatDisposition.DOD_FAILED,
            )


@runtime_checkable
class BeatRunner(Protocol):
    """The one dream call a beat makes (spec 03 §3) — the swappable execution seam (spec 09 §4)."""

    async def run_task(
        self,
        *,
        task_id: str,
        intent: str,
        verification: tuple[VerificationStep, ...] = (),
        rubric: str = "",
        observer: Callable[[Event], None] | None = None,
        run_id: str | None = None,
    ) -> BeatOutcome:
        """Run the task end-to-end, enforcing ``verification`` (the DoD's objective checks).

        ``rubric`` is the DoD's review rubric (spec 16) — dream's single in-beat evaluator judges the
        artefact against it, collapsing the redundant second Reviewer beat into one ``run_task`` verdict.
        ``observer`` witnesses dream's structured run events. ``run_id`` is the chorus run this beat
        executes — threaded so a role's in-beat capability tools learn which run they act under.
        """
        ...


__all__ = [
    "BeatDisposition",
    "BeatOutcome",
    "BeatRunner",
]
