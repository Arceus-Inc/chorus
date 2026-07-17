"""The authored Postgres migration stream — immutable deltas over the frozen baseline.

``schema/*.sql`` is the baseline snapshot that bootstraps *fresh* databases; every schema change
after a database exists ships here as ``migrations/NNNN_name.sql`` — an immutable, Postgres-native
delta applied in id order. ``chorus_schema_migrations`` records the applied set (id + checksum +
applied_at), collision-safe under parallel development: two branches that each add a migration
merge as two rows, never a renumber.

The runner refuses two states rather than guessing:

- **ledger ahead of the SDK** — an applied id the SDK does not ship (upgrade the SDK);
- **checksum drift** — a shipped migration was edited after it was applied somewhere
  (deployed migrations are immutable; author a new one instead).

Deployments whose runtime role cannot run DDL (podium's ``podium_app``) apply pending deltas in
their own migration stream as the schema owner — same statements, via :func:`load_migrations` —
then every later ``Ledger.open`` sees them recorded and skips. Authoring rules: Postgres-native
types, ``company_id`` + FORCE RLS on every new table (copy the house pattern from
``schema/*.sql``), DDL only — data backfills are separate migrations.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from importlib.resources import files

_CREATE_TABLE = re.compile(r"^CREATE TABLE (\w+)", re.I)


def split_statements(sql: str) -> list[str]:
    """``;``-separated statements with ``--`` comments stripped."""
    without_comments = "\n".join(line.split("--", 1)[0] for line in sql.splitlines())
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


__all__ = [
    "LedgerAheadError",
    "Migration",
    "MigrationDriftError",
    "load_migrations",
    "split_statements",
]


class LedgerAheadError(RuntimeError):
    """The database has an applied migration the running SDK does not ship (upgrade the SDK)."""


class MigrationDriftError(RuntimeError):
    """A shipped migration's checksum differs from its applied row (edited after apply)."""


@dataclass(frozen=True)
class Migration:
    """One immutable delta: ``id`` orders it, ``checksum`` pins its exact bytes."""

    id: str
    sql: str = field(repr=False)
    checksum: str = ""  # always derived from the sql bytes in __post_init__

    def __post_init__(self) -> None:
        digest = hashlib.sha256(self.sql.encode("utf-8")).hexdigest()
        object.__setattr__(self, "checksum", digest)

    def statements(self) -> list[str]:
        """The delta's statements (checksum covers the raw bytes, not this normalization)."""
        return split_statements(self.sql)

    def table_names(self) -> list[str]:
        """Tables this delta creates, statement order — deployments grant their runtime role
        exactly these (never a blanket schema grant)."""
        matches = (_CREATE_TABLE.match(statement) for statement in self.statements())
        return [match.group(1) for match in matches if match is not None]


def load_migrations() -> list[Migration]:
    """Every shipped ``migrations/*.sql`` delta, id order (empty while the baseline subsumes all)."""
    directory = files("chorus.ledger.migrations")
    shipped = [
        Migration(id=entry.name.removesuffix(".sql"), sql=entry.read_text())
        for entry in directory.iterdir()
        if entry.name.endswith(".sql")
    ]
    return sorted(shipped, key=lambda migration: migration.id)
