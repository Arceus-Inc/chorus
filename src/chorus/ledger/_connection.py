"""THE ledger connection — psycopg3, Postgres, the only driver (SQLite retired).

Storage is native (uuid/timestamptz/jsonb/boolean); the *wire* stays exactly what the repos speak:

- **out**: uuid/timestamptz/json values load as their canonical text (registered text loaders), so
  ``from_iso``/``loads`` in ``repos/_base`` see the same shapes SQLite returns. Integers, floats and
  booleans load natively (``bool(1)`` and ``bool(True)`` agree).
- **in**: every ``str`` parameter is sent with *unknown* type OID, so the server infers the column
  type from context (uuid text → uuid, ISO text → timestamptz, JSON text → jsonb) — the same
  inference a quoted literal gets. This mirrors SQLite's typeless binds without a single repo change.

Transaction semantics mirror ``sqlite3``'s deferred mode, which the repos were written against:
reads run in autocommit (no idle-in-transaction lingering); the first *write* opens an explicit
transaction that ``commit()``/``rollback()`` closes; the facade's ``transaction()`` batching defers
intermediate commits via the same ``_defer_depth`` latch the SQLite driver uses.
"""

from __future__ import annotations

from typing import Any

import psycopg
from psycopg import rows
from psycopg.abc import AdaptContext
from psycopg.adapt import Loader
from psycopg.types.string import StrDumper

from chorus.ledger._errors import LedgerIntegrityError

_WRITE_PREFIXES = ("INSERT", "UPDATE", "DELETE")


class _InferringStrDumper(StrDumper):
    """Send ``str`` params as *unknown* so Postgres infers the type from the target column."""

    oid = 0  # invalid/unspecified → server-side inference, like a quoted literal


class _TextLoader(Loader):
    """Load a value as its canonical text (uuid, timestamptz, json…)."""

    def load(self, data: bytes | bytearray | memoryview) -> str:
        return bytes(data).decode("utf-8")


def _qmark_to_percent(sql: str) -> str:
    """Translate DB-API qmark placeholders to psycopg's format style, respecting quoted literals.

    Literal ``%`` doubles to ``%%`` (psycopg parses format placeholders whenever params are
    passed); adjacent quotes (``''`` escapes) toggle in-and-out and stay untouched.
    """
    out: list[str] = []
    in_string = False
    for ch in sql:
        if ch == "'":
            in_string = not in_string
            out.append(ch)
        elif ch == "?" and not in_string:
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class LedgerConnection:
    """A psycopg connection presented through the repos' ``LedgerConnection`` protocol."""

    _defer_depth: int = 0  # >0 while a facade transaction is batching writes
    _tx_aborted: bool = False  # latched if any (even nested, caught) block raised

    def __init__(self, pg: psycopg.Connection[Any]) -> None:
        self._pg = pg
        self._in_txn = False

    @classmethod
    def connect(cls, conninfo: str, *, company_id: str | None = None) -> LedgerConnection:
        pg = psycopg.connect(conninfo, autocommit=True, row_factory=rows.dict_row)
        _register_ledger_types(pg)
        if company_id is not None:
            # A dedicated per-company connection: pin the tenancy GUC for the whole session so the
            # RLS policies scope every statement and the DEFAULT stamps every insert. Bound as a
            # parameter — never interpolated.
            pg.execute("SELECT set_config('app.company_id', %s, false)", (company_id,))
        return cls(pg)

    def execute(self, sql: str, parameters: Any = (), /) -> Any:
        query = _qmark_to_percent(sql)
        if query.lstrip()[:6].upper() in _WRITE_PREFIXES:
            return self._execute_write(query, parameters)
        return self._pg.execute(query, parameters or None)

    def _execute_write(self, query: str, parameters: Any) -> Any:
        """A write, with sqlite3's per-statement atomicity inside an open transaction.

        In Postgres any error aborts the WHOLE transaction (every later statement raises
        InFailedSqlTransaction until rollback) — but the kernel's exact-once pattern is
        "try the insert, catch the unique violation, continue". A savepoint around each write
        gives it sqlite semantics: the failed statement rolls back alone, the transaction and
        its prior writes stay live. Constraint violations re-raise as the driver-neutral
        LedgerIntegrityError.
        """
        if not self._in_txn:
            self._pg.execute("BEGIN")  # writes batch until commit(), exactly like sqlite3 deferred
            self._in_txn = True
        self._pg.execute("SAVEPOINT ledger_write")
        try:
            cursor = self._pg.execute(query, parameters or None)
        except psycopg.errors.IntegrityError as exc:
            # ROLLBACK TO resets the subtransaction but leaves it on the stack; RELEASE pops it so
            # a retry-heavy batched transaction never crosses Postgres's 64-sub-XID snapshot cliff.
            self._pg.execute("ROLLBACK TO SAVEPOINT ledger_write")
            self._pg.execute("RELEASE SAVEPOINT ledger_write")
            raise LedgerIntegrityError(str(exc)) from exc
        except Exception:
            self._pg.execute("ROLLBACK TO SAVEPOINT ledger_write")
            self._pg.execute("RELEASE SAVEPOINT ledger_write")
            raise
        self._pg.execute("RELEASE SAVEPOINT ledger_write")
        return cursor

    def commit(self) -> None:
        if self._defer_depth == 0 and self._in_txn:
            self._pg.execute("COMMIT")
            self._in_txn = False

    def rollback(self) -> None:
        if self._in_txn:
            self._pg.execute("ROLLBACK")
            self._in_txn = False

    def close(self) -> None:
        if self._in_txn:  # never leave a dangling transaction on the wire
            self.rollback()
        self._pg.close()


def _register_ledger_types(context: AdaptContext) -> None:
    """Text-out / inferred-in adaptation: native storage, SQLite-shaped wire values."""
    adapters = context.adapters
    adapters.register_dumper(str, _InferringStrDumper)
    for type_name in ("uuid", "timestamptz", "json", "jsonb"):
        adapters.register_loader(type_name, _TextLoader)


__all__ = ["LedgerConnection"]
