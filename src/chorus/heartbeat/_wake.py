"""The wake model + the tick's report shape (spec 03 §2, spec 10 §1).

A ``wake`` is *"run employee E because reason R, payload P."* Dispatch is **push-only**: an
employee runs only when a durable wake row exists (B2.3) — the tick is the sole timer, and it exists
to drain wakes, fire cron, and recover crashes, never to make every employee re-check its inbox.

``Wake``/``WakeReason``/``WakeStatus`` are *durable ledger rows* (spec 01 Cluster C), so they live in
:mod:`chorus.ledger` and are re-exported here for the scheduler (and the public API). ``TickReport``
is a tick-only value and stays here. Keeping the models in the ledger avoids a heartbeat→ledger
import cycle (heartbeat depends on ledger, never the reverse).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from chorus.ledger import Wake, WakeReason, WakeStatus


@dataclass(frozen=True)
class TickReport:
    """What one kernel pulse did (spec 03, spec 10 §1).

    A read projection of a single ``tick`` — the recovery sweep, cron firings, wakes drained, beats
    dispatched (kicked off async, *not* awaited), and how many dispatches a hard-stop budget blocked.
    """

    at: datetime
    recovered: int = 0
    routines_fired: int = 0
    wakes_dispatched: int = 0
    beats_started: int = 0
    blocked_by_budget: int = 0  # dispatches withheld by the concurrency cap (spec 03 §5)
    budget_gated: int = 0  # dispatches withheld by a money-budget hard-stop (spec 04 §3 Gate 1)


__all__ = [
    "TickReport",
    "Wake",
    "WakeReason",
    "WakeStatus",
]
