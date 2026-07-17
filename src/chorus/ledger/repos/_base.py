"""Shared repo helpers (spec 01, Arceus-style per-aggregate repos).

Repos speak the **SQLite ∩ Postgres intersection** over a DB-API connection (spec 12), so the same
repo code runs on both — only the drivers (connection setup, type adaptation, migration DDL) are
dialect-specific. Repos never import a driver: they are typed against the :class:`LedgerConnection`
protocol below, and each driver's connection satisfies it (``test_repo_portability`` enforces the
no-driver-import rule at the source level).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Protocol, TypeVar

_T = TypeVar("_T")


class LedgerRow(Protocol):
    """One result row, readable by column name (sqlite3.Row / psycopg dict_row both satisfy it)."""

    def __getitem__(self, key: str) -> Any: ...


class LedgerCursor(Protocol):
    """The slice of a DB-API cursor the repos actually use."""

    @property
    def rowcount(self) -> int: ...

    def fetchone(self) -> Any: ...

    def fetchall(self) -> list[Any]: ...


class LedgerConnection(Protocol):
    """The driver seam (spec 12 §3): what a ledger driver's connection must provide to the repos.

    ``sqlite3.Connection`` satisfies it natively; the Postgres driver provides an adapter. ``commit``
    may be deferred by the facade's ``transaction()`` batching — repos call it exactly as if each
    write were its own unit.
    """

    def execute(self, sql: str, parameters: Any = (), /) -> LedgerCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...


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
