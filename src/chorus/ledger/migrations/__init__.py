"""The migration set the SDK ships (spec 01 §schema-versioning).

Migrations are plain ``*.sql`` files in this directory (Postgres / golang-migrate style), applied
in filename order by the :class:`~chorus.ledger._migrations.MigrationRunner` and recorded in
``schema_migrations``. **Add a migration by dropping a new numbered ``.sql`` file — no Python edit.**

The *declarative* current schema lives in ``chorus.ledger.schema`` (the ``schema/`` folder); a
parity test asserts that applying these migrations yields exactly that schema, so they never drift.
"""

from __future__ import annotations

from importlib.resources import files

from chorus.ledger._migrations import Migration, load_migrations

MIGRATIONS: tuple[Migration, ...] = load_migrations(files(__name__))

__all__ = ["MIGRATIONS"]
