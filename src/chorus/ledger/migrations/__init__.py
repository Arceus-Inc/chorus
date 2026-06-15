"""The ordered, immutable migration set the SDK ships (spec 01 §schema-versioning).

``MIGRATIONS`` is the single source of truth for the schema the running SDK expects. The
:class:`~chorus.ledger._migrations.MigrationRunner` applies any not yet recorded in the ledger's
``schema_migrations`` table, in ``id`` order. Add a new migration by appending its module here;
never edit a shipped one.
"""

from __future__ import annotations

from chorus.ledger._migrations import Migration
from chorus.ledger.migrations._0001_m1_core import MIGRATION_0001

MIGRATIONS: tuple[Migration, ...] = (MIGRATION_0001,)

__all__ = ["MIGRATIONS"]
