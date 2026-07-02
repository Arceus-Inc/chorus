"""One place for the entity-id convention.

Every ledger entity is identified by ``"<prefix>_<12 hex>"``. This was inlined as
``f"{prefix}_{uuid.uuid4().hex[:12]}"`` at ~50 call sites — a copy-paste convention with no single
source of truth (one site could silently drift to ``[:8]``). :func:`mint_id` is that source.
"""

from __future__ import annotations

import uuid

# The id suffix length (hex chars). 12 hex = 48 bits of entropy — ample for per-org entity ids.
_SUFFIX_LEN = 12


def mint_id(prefix: str) -> str:
    """Return a fresh ``"<prefix>_<12 hex>"`` id (e.g. ``mint_id("wake") -> "wake_a1b2c3d4e5f6"``)."""
    return f"{prefix}_{uuid.uuid4().hex[:_SUFFIX_LEN]}"


__all__ = ["mint_id"]
