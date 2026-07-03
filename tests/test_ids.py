"""chorus.ids.mint_id — the one entity-id convention (spec 01 §1)."""

from __future__ import annotations

import re

import pytest

from chorus.ids import mint_id

pytestmark = pytest.mark.unit


def test_mint_id_has_the_prefix_and_twelve_hex_suffix() -> None:
    minted = mint_id("wake")
    assert re.fullmatch(r"wake_[0-9a-f]{12}", minted)


def test_mint_id_is_unique_per_call() -> None:
    assert len({mint_id("run") for _ in range(1000)}) == 1000
