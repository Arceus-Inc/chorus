"""Budget spend windows (spec 04 §3) — the period the live spend sum covers.

A window never banks unspent budget: :func:`window_start` is the inclusive lower bound the live SQL
sums ``cost_event.occurred_at`` from, so each new window starts the observed sum at zero. ``total``
is a lifetime cap with no lower bound.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

_ROLLING_DAYS = 30


class BudgetWindow(StrEnum):
    """The spend window a :class:`~chorus.ledger.BudgetPolicy` sums cost events over (spec 04 §3)."""

    MONTHLY = "monthly"
    WEEKLY = "weekly"
    ROLLING_30D = "rolling_30d"
    TOTAL = "total"


def window_start(window: BudgetWindow, now: datetime) -> datetime | None:
    """The inclusive lower bound of ``window`` at ``now``, or ``None`` for a lifetime (``total``) cap."""
    if window is BudgetWindow.TOTAL:
        return None
    if window is BudgetWindow.ROLLING_30D:
        return now - timedelta(days=_ROLLING_DAYS)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if window is BudgetWindow.WEEKLY:
        return midnight - timedelta(days=now.weekday())  # back to Monday
    return midnight.replace(day=1)  # MONTHLY — first of the month
