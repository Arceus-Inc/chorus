"""``PostgresLedger`` — the Arceus-distribution :class:`~chorus.ledger.Ledger` driver (spec 12 §6).

Same repos, same cross-aggregate atomics (via :class:`~chorus.ledger._core.LedgerCore`), native
Postgres storage (uuid / timestamptz / jsonb / boolean — see ``_ddl``). ``open`` connects, bootstraps
the schema under an advisory lock, and wires the repos.

Schema versioning: the translated DDL is applied as one **baseline** whose checksum is recorded in
``chorus_schema_migrations``. A checksum mismatch on open means the declarative schema evolved after
this database was created — with no released Postgres deployments the correct move is a fresh
bootstrap (drop + reopen); once deployments exist, authored Postgres migrations take over from the
baseline (the applied-set model is already in place for them).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from chorus.ledger._core import LedgerCore
from chorus.ledger.postgres._connection import PostgresLedgerConnection
from chorus.ledger.postgres._ddl import postgres_ddl

_BASELINE_ID = "0001_baseline"
_ADVISORY_LOCK_KEY = 0x43484F52  # 'CHOR' — serialises concurrent bootstrap attempts

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS chorus_schema_migrations (
    id         text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL
)
"""


class SchemaDriftError(RuntimeError):
    """The declarative schema changed after this database was baselined (checksum mismatch)."""


def _baseline_checksum(statements: list[str]) -> str:
    digest = hashlib.sha256()
    for statement in statements:
        digest.update(statement.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


class PostgresLedger(LedgerCore):
    """The Postgres-backed :class:`~chorus.ledger.Ledger` (spec 12 §6)."""

    def __init__(self, conn: PostgresLedgerConnection) -> None:
        self._pg_conn = conn
        self._schema_version: str | None = None
        super().__init__(conn)

    @classmethod
    def open(cls, conninfo: str) -> PostgresLedger:
        """Connect, bootstrap (idempotent, advisory-locked), and wire the repos."""
        conn = PostgresLedgerConnection.connect(conninfo)
        ledger = cls(conn)
        ledger._bootstrap()
        return ledger

    def _bootstrap(self) -> None:
        statements = postgres_ddl()
        checksum = _baseline_checksum(statements)
        pg = self._pg_conn._pg
        # One explicit transaction for the whole bootstrap; the advisory lock is transaction-scoped,
        # so two processes opening together serialise and the loser sees the recorded baseline.
        with pg.transaction():
            pg.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_KEY,))
            pg.execute(_SCHEMA_MIGRATIONS_DDL)
            row = pg.execute(
                "SELECT checksum FROM chorus_schema_migrations WHERE id = %s", (_BASELINE_ID,)
            ).fetchone()
            if row is not None:
                if row["checksum"] != checksum:
                    raise SchemaDriftError(
                        "the declarative ledger schema changed after this database was baselined; "
                        "re-bootstrap the database (no authored Postgres migrations exist yet)"
                    )
                self._schema_version = _BASELINE_ID
                return
            for statement in statements:
                pg.execute(statement)
            pg.execute(
                "INSERT INTO chorus_schema_migrations (id, checksum, applied_at) "
                "VALUES (%s, %s, %s)",
                (_BASELINE_ID, checksum, datetime.now(UTC)),
            )
        self._schema_version = _BASELINE_ID

    def schema_version(self) -> str | None:
        return self._schema_version

    def close(self) -> None:
        self._pg_conn.close()


__all__ = ["PostgresLedger", "SchemaDriftError"]
