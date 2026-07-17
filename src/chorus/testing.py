"""Test helpers shipped with the SDK (the suite runs on real Postgres — SQLite is retired).

``uid(name)`` turns a readable fixture handle into deterministic canonical-uuid text:
``uid("t1")`` is always the same uuid, so cross-references inside a test line up, while the
ledger's native uuid columns get the shape they enforce. Every test runs in its own
template-copied database, so identical ids across tests can never collide.
"""

from __future__ import annotations

import uuid

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "chorus-test-ids")


def uid(name: str) -> str:
    """Deterministic canonical uuid text for a readable test handle (e.g. ``uid("t1")``)."""
    return str(uuid.uuid5(_NAMESPACE, name))


__all__ = ["uid"]
