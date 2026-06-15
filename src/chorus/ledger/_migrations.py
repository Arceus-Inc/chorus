"""Applied-migration-set versioning + a forward-only runner (spec 01 §schema-versioning).

Versioning tracks the *set* of applied migrations (``id`` + ``checksum``), not a single
integer — collision-safe under parallel development (two branches that each add a migration
merge as two rows, never a renumber). The runner applies every shipped migration whose ``id``
is not yet recorded, in ``id`` order, each in its own transaction. It refuses to run when:

- the ledger is **ahead of the SDK** — an applied ``id`` the SDK does not ship; or
- a shipped migration's **checksum drifted** — it was edited after it was applied.

A derived display version (``max(id)``) is exposed for logs and ``chorus inspect`` — presentation
only, never the source of truth. See spec 01 and spec 12.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from chorus.errors import ChorusError

__all__ = [
    "LedgerAheadError",
    "Migration",
    "MigrationDriftError",
    "MigrationError",
    "MigrationRunner",
]

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    id         TEXT PRIMARY KEY,
    checksum   TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


class MigrationError(ChorusError):
    """Base for migration / versioning failures."""


class LedgerAheadError(MigrationError):
    """The ledger has an applied migration the running SDK does not ship (upgrade the SDK)."""


class MigrationDriftError(MigrationError):
    """A shipped migration's checksum differs from the applied row (edited after apply)."""


@dataclass(frozen=True)
class Migration:
    """One forward-only schema change, identified by a sortable id.

    ``id`` is sequence/timestamp-prefixed + slug (e.g. ``0001_m1_core``) so two branches that
    each add a migration merge as two rows. ``statements`` run in order in a single transaction.
    """

    id: str
    statements: tuple[str, ...]

    @property
    def checksum(self) -> str:
        """Stable, content-sensitive digest of the migration's statements."""
        digest = hashlib.sha256()
        for stmt in self.statements:
            digest.update(stmt.encode("utf-8"))
            digest.update(b"\x00")
        return digest.hexdigest()


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class MigrationRunner:
    """Applies an ordered, immutable set of :class:`Migration` to a SQLite ledger."""

    def __init__(self, migrations: Sequence[Migration]) -> None:
        self._migrations: tuple[Migration, ...] = tuple(sorted(migrations, key=lambda m: m.id))
        ids = [m.id for m in self._migrations]
        if len(ids) != len(set(ids)):
            raise MigrationError(f"duplicate migration id(s): {ids}")

    def applied(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Return ``{id: checksum}`` for migrations recorded in the ledger."""
        self._ensure_table(conn)
        rows = conn.execute("SELECT id, checksum FROM schema_migrations").fetchall()
        return {str(row[0]): str(row[1]) for row in rows}

    def pending(self, conn: sqlite3.Connection) -> list[str]:
        """Ids the SDK ships that are not yet applied, in id order."""
        applied = self.applied(conn)
        return [m.id for m in self._migrations if m.id not in applied]

    def display_version(self, conn: sqlite3.Connection) -> str | None:
        """The highest applied migration id — presentation only, never the source of truth."""
        self._ensure_table(conn)
        row = conn.execute("SELECT MAX(id) FROM schema_migrations").fetchone()
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def apply(self, conn: sqlite3.Connection) -> list[str]:
        """Apply every pending migration in id order; return the ids applied this call.

        Refuses on a ledger ahead of the SDK (:class:`LedgerAheadError`) or a checksum
        mismatch (:class:`MigrationDriftError`). Each migration runs in its own transaction:
        a failure rolls back its statements and leaves ``schema_migrations`` untouched.
        """
        applied = self.applied(conn)
        self._gate(applied)

        newly: list[str] = []
        prev_isolation = conn.isolation_level
        conn.isolation_level = None  # take manual transaction control
        try:
            for migration in self._migrations:
                if migration.id in applied:
                    continue
                conn.execute("BEGIN")
                try:
                    for stmt in migration.statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (id, checksum, applied_at) VALUES (?, ?, ?)",
                        (migration.id, migration.checksum, _utcnow_iso()),
                    )
                    conn.execute("COMMIT")
                except Exception:
                    conn.execute("ROLLBACK")
                    raise
                newly.append(migration.id)
        finally:
            conn.isolation_level = prev_isolation
        return newly

    def _gate(self, applied: dict[str, str]) -> None:
        shipped = {m.id: m.checksum for m in self._migrations}
        for applied_id in applied:
            if applied_id not in shipped:
                raise LedgerAheadError(
                    f"ledger has migration {applied_id!r} the SDK does not ship; upgrade the SDK"
                )
        for migration in self._migrations:
            recorded = applied.get(migration.id)
            if recorded is not None and recorded != migration.checksum:
                raise MigrationDriftError(
                    f"migration {migration.id!r} changed after it was applied (checksum mismatch)"
                )

    def _ensure_table(self, conn: sqlite3.Connection) -> None:
        conn.execute(_SCHEMA_MIGRATIONS_DDL)
        conn.commit()
