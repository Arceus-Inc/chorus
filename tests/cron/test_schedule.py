"""Schedule — a typed builder for cron strings (so nobody hand-writes ``"0 9 * * 1"``).

Each builder validates its inputs and returns a plain 5-field cron string, so it drops straight into
``org.routines.add(schedule=…)`` / ``RoutineDeclaration(schedule=…)``. Storage and firing are unchanged
— this is purely an ergonomic front door over the same cron text.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from chorus.cron import Schedule, Weekday, parse_cron

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("built", "expected"),
    [
        (Schedule.hourly(), "0 * * * *"),
        (Schedule.hourly(minute=30), "30 * * * *"),
        (Schedule.every_minutes(15), "*/15 * * * *"),
        (Schedule.every_hours(6), "0 */6 * * *"),
        (Schedule.daily(at="09:00"), "0 9 * * *"),
        (Schedule.daily(at="9:05"), "5 9 * * *"),
        (Schedule.weekdays(at="09:00"), "0 9 * * 1-5"),
        (Schedule.weekly(Weekday.MONDAY, at="09:00"), "0 9 * * 1"),
        (Schedule.weekly(Weekday.SUNDAY, at="00:00"), "0 0 * * 0"),
        (Schedule.monthly(day=1, at="09:00"), "0 9 1 * *"),
        (Schedule.cron("0 9 * * 1"), "0 9 * * 1"),
    ],
)
def test_builders_emit_the_expected_cron(built: str, expected: str) -> None:
    assert built == expected


def test_weekday_maps_to_cron_numbers() -> None:
    assert Weekday.MONDAY == 1
    assert Weekday.SUNDAY == 0


def test_every_built_string_is_a_valid_cron() -> None:
    base = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)  # a Monday
    for built in (
        Schedule.hourly(minute=30),
        Schedule.every_minutes(15),
        Schedule.every_hours(6),
        Schedule.daily(at="09:00"),
        Schedule.weekdays(at="09:00"),
        Schedule.weekly(Weekday.FRIDAY, at="17:30"),
        Schedule.monthly(day=28, at="06:00"),
    ):
        assert parse_cron(built, base=base) > base  # parses + yields a future edge


@pytest.mark.parametrize(
    "call",
    [
        lambda: Schedule.daily(at="25:00"),
        lambda: Schedule.daily(at="09:61"),
        lambda: Schedule.daily(at="0900"),
        lambda: Schedule.daily(at="nope"),
        lambda: Schedule.every_minutes(0),
        lambda: Schedule.every_minutes(60),
        lambda: Schedule.every_hours(0),
        lambda: Schedule.every_hours(24),
        lambda: Schedule.hourly(minute=60),
        lambda: Schedule.monthly(day=0, at="09:00"),
        lambda: Schedule.monthly(day=32, at="09:00"),
        lambda: Schedule.cron("0 9 * *"),  # only 4 fields
    ],
)
def test_bad_inputs_are_rejected(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]
