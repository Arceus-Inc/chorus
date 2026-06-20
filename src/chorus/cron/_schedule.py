"""Schedule — a typed builder for cron strings (spec 13).

Writing ``"0 9 * * 1"`` by hand is opaque and easy to get wrong. :class:`Schedule` builds the same
5-field cron text from named, validated parameters — ``Schedule.weekly(Weekday.MONDAY, at="09:00")``
instead of the raw string. It returns a plain ``str``, so it drops straight into
``org.routines.add(schedule=…)`` and ``RoutineDeclaration(schedule=…)``; storage and the firing engine
are unchanged. ``Schedule.cron(...)`` is the escape hatch for an expression the builders don't cover.

This module is pure stdlib — it never imports dream. Semantic cron validation still happens downstream
(``parse_cron`` at ``add_routine`` / plugin registration); the builders just guarantee well-formed,
in-range fields up front.
"""

from __future__ import annotations

from enum import IntEnum

# cron day-of-week numbering: 0 = Sunday … 6 = Saturday (Monday = 1).
_WEEKDAYS_FIELD = "1-5"  # Monday-Friday


class Weekday(IntEnum):
    """A day of the week, valued as its cron day-of-week number (Sunday = 0)."""

    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 0


class Schedule:
    """Builders that return a 5-field cron string. All staticmethods — never instantiated."""

    @staticmethod
    def cron(expression: str) -> str:
        """An explicit cron expression (escape hatch). Checks it has 5 fields; the semantics are
        validated downstream by ``parse_cron`` at add/registration time."""
        if len(expression.split()) != 5:
            raise ValueError(
                f"a cron expression must have 5 fields (min hour day month weekday), got {expression!r}"
            )
        return expression

    @staticmethod
    def every_minutes(n: int) -> str:
        """Every ``n`` minutes (1-59), e.g. ``every_minutes(15)`` → ``*/15 * * * *``."""
        _require_range(n, 1, 59, "every_minutes")
        return f"*/{n} * * * *"

    @staticmethod
    def hourly(*, minute: int = 0) -> str:
        """Once an hour at ``minute`` (0-59), e.g. ``hourly(minute=30)`` → ``30 * * * *``."""
        _require_range(minute, 0, 59, "minute")
        return f"{minute} * * * *"

    @staticmethod
    def every_hours(n: int) -> str:
        """Every ``n`` hours (1-23) on the hour, e.g. ``every_hours(6)`` → ``0 */6 * * *``."""
        _require_range(n, 1, 23, "every_hours")
        return f"0 */{n} * * *"

    @staticmethod
    def daily(*, at: str) -> str:
        """Once a day at ``at`` (``"HH:MM"``), e.g. ``daily(at="09:00")`` → ``0 9 * * *``."""
        hour, minute = _parse_at(at)
        return f"{minute} {hour} * * *"

    @staticmethod
    def weekdays(*, at: str) -> str:
        """Monday-Friday at ``at`` (``"HH:MM"``), e.g. ``weekdays(at="09:00")`` → ``0 9 * * 1-5``."""
        hour, minute = _parse_at(at)
        return f"{minute} {hour} * * {_WEEKDAYS_FIELD}"

    @staticmethod
    def weekly(day: Weekday, *, at: str) -> str:
        """Weekly on ``day`` at ``at``, e.g. ``weekly(Weekday.MONDAY, at="09:00")`` → ``0 9 * * 1``."""
        hour, minute = _parse_at(at)
        return f"{minute} {hour} * * {day.value}"

    @staticmethod
    def monthly(*, day: int, at: str) -> str:
        """Monthly on day-of-month ``day`` (1-31) at ``at``, e.g. ``monthly(day=1, at="09:00")`` →
        ``0 9 1 * *``."""
        _require_range(day, 1, 31, "day")
        hour, minute = _parse_at(at)
        return f"{minute} {hour} {day} * *"


def _parse_at(at: str) -> tuple[int, int]:
    """Parse ``"HH:MM"`` into validated ``(hour, minute)``."""
    parts = at.split(":")
    if len(parts) != 2 or not all(p.strip().isdigit() for p in parts):
        raise ValueError(f"time must be 'HH:MM', got {at!r}")
    hour, minute = int(parts[0]), int(parts[1])
    _require_range(hour, 0, 23, "hour")
    _require_range(minute, 0, 59, "minute")
    return hour, minute


def _require_range(value: int, low: int, high: int, name: str) -> None:
    if not low <= value <= high:
        raise ValueError(f"{name} must be between {low} and {high}, got {value}")


__all__ = ["Schedule", "Weekday"]
