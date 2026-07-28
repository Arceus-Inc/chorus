"""The CHORUS_TCP rollout flag.

Pure, so these run without Postgres. The environment is injected rather than mutated: a test that
sets ``os.environ`` leaks into every other test in the session, and this flag is read from inside the
kernel where that leak would be invisible.
"""

from __future__ import annotations

import pytest

from chorus.context import TCP_ENV_VAR, tcp_enabled


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " 1 "])
def test_truthy_values_enable_the_packet(value: str) -> None:
    assert tcp_enabled({TCP_ENV_VAR: value}) is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_everything_else_leaves_it_off(value: str) -> None:
    assert tcp_enabled({TCP_ENV_VAR: value}) is False


def test_absent_variable_is_off() -> None:
    """Default off is the whole point: an unflagged company behaves exactly as it did before."""
    assert tcp_enabled({}) is False
