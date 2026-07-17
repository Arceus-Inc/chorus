"""One place for the entity-id convention.

Every ledger entity is identified by **canonical uuidv7 text** (RFC 9562): 128-bit unique, so a
native Postgres ``uuid`` column stores it directly (spec 12 §6), and time-ordered, so B-tree inserts
stay append-mostly on both engines. The old ``"<prefix>_<12 hex>"`` shape (48 bits, unparseable as
uuid) is gone — the column names the kind; the id doesn't need to.

Implemented locally because the runtime targets Python < 3.14 (no ``uuid.uuid7`` in the stdlib):
48-bit unix-millisecond timestamp, then version/variant bits, then 74 random bits, per RFC 9562 §5.7.
"""

from __future__ import annotations

import secrets
import time
import uuid


def _uuid7() -> uuid.UUID:
    """A random-tail uuidv7: ``unix_ts_ms(48) | ver(4) | rand_a(12) | var(2) | rand_b(62)``."""
    timestamp_ms = time.time_ns() // 1_000_000
    value = (timestamp_ms & 0xFFFF_FFFF_FFFF) << 80
    value |= 0x7 << 76  # version 7
    value |= secrets.randbits(12) << 64  # rand_a
    value |= 0b10 << 62  # RFC 4122/9562 variant
    value |= secrets.randbits(62)  # rand_b
    return uuid.UUID(int=value)


def mint_id() -> str:
    """Return a fresh entity id: canonical uuidv7 text (e.g. ``"01912e5a-…-b3d4"``)."""
    return str(_uuid7())


def derive_id(*parts: str) -> str:
    """A DETERMINISTIC entity id from stable parts (uuid5) — for idempotent re-derivable rows
    (e.g. the once-per-beat plan-revision artifact keyed on its run id). Same parts, same id."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "chorus-derived:" + "\x1f".join(parts)))


__all__ = ["derive_id", "mint_id"]
