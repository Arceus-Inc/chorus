"""Budget spend windows (spec 04 §3) — the period the live spend sum covers.

A window never banks unspent budget: ``window_start`` is the inclusive lower bound the live SQL sums
``cost_event.occurred_at`` from, so each new window starts the observed sum at zero.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from chorus.budgets import BudgetWindow, window_start

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 6, 16, 14, 30, tzinfo=UTC)  # a Tuesday afternoon


def test_monthly_starts_at_first_of_month_midnight() -> None:
    assert window_start(BudgetWindow.MONTHLY, _NOW) == datetime(2026, 6, 1, tzinfo=UTC)


def test_weekly_starts_at_monday_midnight() -> None:
    start = window_start(BudgetWindow.WEEKLY, _NOW)
    assert start is not None
    assert start.weekday() == 0  # Monday
    assert start.hour == 0 and start.minute == 0
    assert start <= _NOW and (_NOW - start) < timedelta(days=7)


def test_rolling_30d_is_thirty_days_back() -> None:
    assert window_start(BudgetWindow.ROLLING_30D, _NOW) == _NOW - timedelta(days=30)


def test_total_has_no_lower_bound() -> None:
    assert window_start(BudgetWindow.TOTAL, _NOW) is None
