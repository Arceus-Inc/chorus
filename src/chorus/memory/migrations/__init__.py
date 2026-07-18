"""The episodic migration set (spec 07). Mirrors ``chorus.ledger.migrations``.

Plain ``*.sql`` files in this directory, applied in filename order by the (shared, dialect-agnostic)
:class:`~chorus.ledger._migrations.MigrationRunner`. **Add a migration by dropping a new numbered
``.sql`` file — no Python edit.** The *declarative* current schema lives in ``chorus.memory.schema``;
``tests/memory/test_schema_parity`` asserts these two never drift.
"""

from __future__ import annotations

from importlib.resources import files

from chorus._sqlite_migrations import Migration, load_migrations

MIGRATIONS: tuple[Migration, ...] = load_migrations(files(__name__))

__all__ = ["MIGRATIONS"]
