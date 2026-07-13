"""Skills migration set — plain ``*.sql`` files, applied by MigrationRunner."""

from __future__ import annotations

from importlib.resources import files

from chorus.ledger._migrations import Migration, load_migrations

MIGRATIONS: tuple[Migration, ...] = load_migrations(files(__name__))

__all__ = ["MIGRATIONS"]
