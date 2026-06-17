"""The four-way failure contract — classify a raise out of a beat into a typed disposition (spec 05 §5).

Used by :class:`DreamBeatRunner` (the one beat seam, over ``run_task``): a raise is classified
**structurally** off dream's stable error contract (``code``/``phase``) so the adapter never imports
dream. ``asyncio.CancelledError`` is re-raised by the caller and never reaches here.
"""

from __future__ import annotations

from chorus.heartbeat._beat import BeatDisposition, BeatOutcome


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
    )


__all__ = ["failure_outcome"]
