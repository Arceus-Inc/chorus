"""Example-smoke harness: every smoke runs against a fresh test-cluster database as a
NON-superuser role so FORCE RLS scopes companies exactly as in production (a superuser
would bypass row security and cross-company slug checks would leak)."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

from chorus.testing import open_test_ledger


@pytest.fixture(autouse=True)
def _example_dsn(pg_conninfo: str) -> Iterator[None]:
    import psycopg

    store = open_test_ledger()
    dsn = store._conn._pg.info.dsn
    store.close()
    with psycopg.connect(pg_conninfo, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'demo_app') "
            "THEN CREATE ROLE demo_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
    with psycopg.connect(dsn, autocommit=True) as db_admin:
        db_admin.execute("GRANT USAGE ON SCHEMA public TO demo_app")
        db_admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO demo_app"
        )
    previous = os.environ.get("CHORUS_LEDGER_DSN")
    os.environ["CHORUS_LEDGER_DSN"] = dsn.replace("user=postgres", "user=demo_app")
    yield
    if previous is None:
        os.environ.pop("CHORUS_LEDGER_DSN", None)
    else:
        os.environ["CHORUS_LEDGER_DSN"] = previous
