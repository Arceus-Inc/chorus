"""The driver-neutral ledger exception vocabulary.

The kernel's exact-once semantics lean on unique indexes: a duplicate insert *raises*, and the
caller either resumes idempotently (horizon intake, routine firing) or propagates. That catch must
be driver-neutral — SQLite raises ``sqlite3.IntegrityError``, Postgres raises
``psycopg.errors.UniqueViolation`` — so both drivers translate their native error into
:class:`LedgerIntegrityError` at the connection seam.

It subclasses ``sqlite3.IntegrityError`` (stdlib — not a driver dependency) so every pre-existing
``except sqlite3.IntegrityError`` in SDK consumers keeps working; new code catches the canonical
name.
"""

from __future__ import annotations

import sqlite3


class LedgerIntegrityError(sqlite3.IntegrityError):
    """A constraint violation from any ledger driver (unique/FK/NOT NULL)."""


__all__ = ["LedgerIntegrityError"]
