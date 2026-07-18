"""chorus.ids.mint_id — the one entity-id convention (spec 01 §1, spec 12 §6 Postgres-native).

Ids are canonical uuidv7 text: parseable by a native Postgres ``uuid`` column, 128-bit unique,
and time-ordered (B-tree-friendly on both engines). No prefixes — the column names the kind.
"""

from __future__ import annotations

import time
import uuid

import pytest

from chorus.ids import mint_id

pytestmark = pytest.mark.unit


def test_mint_id_is_canonical_uuid7_text() -> None:
    minted = mint_id()
    parsed = uuid.UUID(minted)  # native uuid columns accept it — raises on any non-uuid shape
    assert str(parsed) == minted  # canonical lowercase text, round-trips exactly
    assert parsed.version == 7  # time-ordered, never random-v4


def test_mint_id_is_unique_per_call() -> None:
    assert len({mint_id() for _ in range(10_000)}) == 10_000


def test_mint_id_is_time_ordered_across_a_millisecond() -> None:
    earlier = mint_id()
    time.sleep(0.002)  # cross the uuidv7 millisecond boundary
    later = mint_id()
    assert earlier < later  # lexicographic == chronological (uuidv7's point)
