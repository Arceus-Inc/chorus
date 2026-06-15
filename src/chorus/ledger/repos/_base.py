"""Shared repo helpers (spec 01, Arceus-style per-aggregate repos).

Repos speak the **SQLite ∩ Postgres intersection** over a DB-API connection (spec 12), so the same
repo code runs on Postgres later — only the connection setup + migration DDL are dialect-specific.
Timestamps are ISO-8601 text; JSON columns are compact text. The facade sets ``sqlite3.Row`` so
repos read columns by name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


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
