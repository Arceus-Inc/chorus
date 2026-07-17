"""Test helpers shipped with the SDK (the suite runs on real Postgres — SQLite is retired).

``uid(name)`` turns a readable fixture handle into deterministic canonical-uuid text:
``uid("t1")`` is always the same uuid, so cross-references inside a test line up, while the
ledger's native uuid columns get the shape they enforce. Every test runs in its own
template-copied database, so identical ids across tests can never collide.
"""

from __future__ import annotations

import uuid

_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "chorus-test-ids")


def uid(name: str) -> str:
    """Deterministic canonical uuid text for a readable test handle (e.g. ``uid("t1")``)."""
    return str(uuid.uuid5(_NAMESPACE, name))


_db_counter = {"n": 0}


def open_test_ledger(company_id: str | None = None) -> object:
    """A standalone Ledger on the test cluster (root conftest exports CHORUS_TEST_PG): a fresh
    template-copied database per call, scoped to a fresh company unless one is given. The
    ephemeral cluster's teardown reclaims everything — no per-ledger cleanup needed."""
    import os

    import psycopg

    from chorus.ledger import Ledger

    conninfo = os.environ.get("CHORUS_TEST_PG")
    if not conninfo:
        raise RuntimeError("CHORUS_TEST_PG is unset — the test cluster fixture is not active")
    _db_counter["n"] += 1
    dbname = f"chorus_adhoc_{os.getpid()}_{_db_counter['n']}"
    with psycopg.connect(conninfo, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {dbname} TEMPLATE chorus_template")
    return Ledger.open(
        conninfo.replace("dbname=postgres", f"dbname={dbname}"),
        company_id=company_id or uid(f"adhoc-{_db_counter['n']}-{os.getpid()}"),
    )


__all__ = ["open_test_ledger", "uid"]
