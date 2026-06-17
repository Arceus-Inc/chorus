"""The four-way failure contract — classify a raise out of a beat into a typed disposition (spec 05 §5).

Used by :class:`DreamBeatRunner` (the one beat seam, over ``run_task``): a raise is classified
**structurally** off dream's stable error contract (``code``/``phase``) so the adapter never imports
dream. ``asyncio.CancelledError`` is re-raised by the caller and never reaches here.
"""

from __future__ import annotations

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome

# A ``*HeadParseError`` is dream's planner/evaluator/generator emitting unparseable structured output —
# a transient model blip that a re-run usually clears. Matched by class name (structural, no dream
# import), consistent with how this module reads dream's error contract.
_TRANSIENT_SUFFIX = "HeadParseError"


def _is_transient(exc: BaseException) -> bool:
    """True for a retryable, transient fault (a head parse blip) — re-running the beat tends to fix it."""
    return type(exc).__name__.endswith(_TRANSIENT_SUFFIX)


def failure_outcome(exc: BaseException) -> BeatOutcome:
    """Classify a beat raise: a ``dream.cancelled`` is a cooperative cancel; anything else is errored."""
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
        retryable=_is_transient(exc),
    )


__all__ = ["failure_outcome"]
