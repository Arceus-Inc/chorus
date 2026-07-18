"""Shared repo helpers (spec 01, Arceus-style per-aggregate repos).

Repos speak plain SQL over the one concrete :class:`~chorus.ledger._connection.LedgerConnection`
(psycopg / Postgres — SQLite is retired). Timestamps travel as ISO text (the connection loads
timestamptz back as canonical text), JSON as compact text into jsonb.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, TypeVar

from chorus.ledger._connection import LedgerConnection

_T = TypeVar("_T")

# One driver: the concrete psycopg connection. Rows are psycopg dict_row mappings.
LedgerRow = Mapping[str, Any]


class LedgerInvariantError(RuntimeError):
    """A row expected to exist (e.g. just written in this transaction) was not found — a corrupt
    store or a broken write, never a normal outcome."""


def utcnow_iso() -> str:
    """Current UTC time as an ISO-8601 string (the ledger's timestamp format)."""
    return datetime.now(UTC).isoformat()


def to_iso(value: datetime | str | None) -> str | None:
    """Normalise a datetime (or already-ISO string) to stored ISO text."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def from_iso(value: str | None) -> datetime | None:
    """Parse stored ISO text back to a datetime (or ``None``)."""
    return datetime.fromisoformat(value) if value else None


def dumps(value: Any) -> str:
    """Compact, stable JSON for a text JSON column."""
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def loads(value: str | None) -> Any:
    """Parse a text JSON column (``None`` → ``None``)."""
    return json.loads(value) if value else None


def loads_dict(value: str | None) -> dict[str, Any]:
    """Parse a JSON object column, defaulting empty/``None`` to ``{}`` (was ``loads(x) or {}``)."""
    parsed = loads(value)
    return parsed if isinstance(parsed, dict) else {}


def loads_list(value: str | None) -> list[Any]:
    """Parse a JSON array column, defaulting empty/``None`` to ``[]`` (was ``loads(x) or []``)."""
    parsed = loads(value)
    return parsed if isinstance(parsed, list) else []


def require_persisted(value: _T | None, entity_id: str) -> _T:
    """Return ``value``, or raise if a just-written row came back missing (replaces the
    ``assert opened is not None`` post-insert guards — asserts vanish under ``python -O``)."""
    if value is None:
        raise LedgerInvariantError(f"row {entity_id!r} not found immediately after write")
    return value


__all__ = [
    "LedgerConnection",
    "LedgerInvariantError",
    "LedgerRow",
    "dumps",
    "from_iso",
    "loads",
    "loads_dict",
    "loads_list",
    "require_persisted",
    "to_iso",
    "utcnow_iso",
]
