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
from importlib.resources.abc import Traversable

from chorus.errors import ChorusError

__all__ = [
    "LedgerAheadError",
    "Migration",
    "MigrationDriftError",
    "MigrationError",
    "MigrationRunner",
    "load_migrations",
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


def _split_statements(sql: str) -> list[str]:
    """Split a ``.sql`` migration into individual statements (``;``-separated).

    Drops ``--`` line comments and blank chunks. The shipped DDL keeps ``;`` only at statement
    boundaries (none inside CHECK/WHERE clauses), so a plain split is correct and keeps each
    statement runnable under the runner's per-migration transaction.
    """
    # Strip ``--`` line comments first, so a ``;`` inside a comment never splits a statement.
    # (The shipped DDL has no ``--`` inside string literals.)
    without_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


def load_migrations(directory: Traversable) -> tuple[Migration, ...]:
    """Load ``*.sql`` migrations from a package directory, ordered by filename (Postgres-style).

    Each file is one migration: its ``id`` is the filename without ``.sql`` (e.g. ``0001_m1_core``),
    its statements are the ``;``-separated DDL. Adding a migration is dropping a new numbered
    ``.sql`` file — no Python edit. The declarative current schema lives in ``chorus.ledger.schema``;
    a parity test asserts applying these yields exactly that schema.
    """
    sql_files = sorted(
        (entry for entry in directory.iterdir() if entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    return tuple(
        Migration(id=entry.name[:-4], statements=tuple(_split_statements(entry.read_text())))
        for entry in sql_files
    )


class MigrationRunner:
    """Applies an ordered, immutable set of :class:`Migration` to a SQLite ledger."""

    def __init__(self, migrations: Sequence[Migration]) -> None:
        self._migrations: tuple[Migration, ...] = tuple(sorted(migrations, key=lambda m: m.id))
        ids = [m.id for m in self._migrations]
        if len(ids) != len(set(ids)):
            raise MigrationError(f"duplicate migration id(s): {ids}")

    def applied(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Return ``{id: checksum}`` recorded in the ledger (``{}`` if the table doesn't exist yet).

        Read-only: never creates the table or commits the caller's connection.
        """
        try:
            rows = conn.execute("SELECT id, checksum FROM schema_migrations").fetchall()
        except sqlite3.OperationalError:
            return {}
        return {str(row[0]): str(row[1]) for row in rows}

    def pending(self, conn: sqlite3.Connection) -> list[str]:
        """Ids the SDK ships that are not yet applied, in id order."""
        applied = self.applied(conn)
        return [m.id for m in self._migrations if m.id not in applied]

    def display_version(self, conn: sqlite3.Connection) -> str | None:
        """The highest applied migration id — presentation only; read-only (``None`` if none)."""
        try:
            row = conn.execute("SELECT MAX(id) FROM schema_migrations").fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None or row[0] is None:
            return None
        return str(row[0])

    def apply(self, conn: sqlite3.Connection) -> list[str]:
        """Apply every pending migration in id order; return the ids applied this call.

        Refuses on a ledger ahead of the SDK (:class:`LedgerAheadError`) or a checksum mismatch
        (:class:`MigrationDriftError`). Each migration runs under ``BEGIN IMMEDIATE`` — the write
        lock is taken *before* deciding, and the migration is re-checked against
        ``schema_migrations`` inside that lock — so two processes starting together can't
        double-apply: the loser sees it already applied and skips. A failed migration rolls back
        its statements and leaves ``schema_migrations`` untouched.
        """
        prev_isolation = conn.isolation_level
        conn.isolation_level = None  # explicit transaction control — no implicit commits
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_table(conn)
            conn.execute("COMMIT")

            applied = self.applied(conn)
            self._gate(applied)

            newly: list[str] = []
            for migration in self._migrations:
                if migration.id in applied:
                    continue
                conn.execute("BEGIN IMMEDIATE")  # write lock taken before deciding
                try:
                    already = conn.execute(
                        "SELECT 1 FROM schema_migrations WHERE id = ?", (migration.id,)
                    ).fetchone()
                    if already is not None:  # a racing process applied it — skip, never re-run
                        conn.execute("COMMIT")
                        continue
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
            return newly
        finally:
            conn.isolation_level = prev_isolation

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
        """Create ``schema_migrations`` if absent. No commit — the caller owns the transaction."""
        conn.execute(_SCHEMA_MIGRATIONS_DDL)
