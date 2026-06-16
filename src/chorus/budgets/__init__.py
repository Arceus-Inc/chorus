"""Two-gate budget enforcement (spec 04 §3).

The hard-stop the org runs on: Gate 1 blocks a beat before it starts when its scope is paused or
over; Gate 2 reacts to each cost event by raising incidents and, on a hard breach, pausing the scope
and killing live work. Spend is always recomputed live from ``cost_event`` — never a stored counter.
"""

from __future__ import annotations

from chorus.budgets._enforcer import BlockReason, BudgetEnforcer
from chorus.budgets._window import BudgetWindow, window_start

__all__ = [
    "BlockReason",
    "BudgetEnforcer",
    "BudgetWindow",
    "window_start",
]
