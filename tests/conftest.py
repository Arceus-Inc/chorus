"""Root fixtures: the throwaway PostgreSQL 18 cluster every test's ledger lives on.

SQLite is retired — the ledger is Postgres-only, so the whole suite runs against a real cluster
(initdb + pg_ctl, no Docker). Bootstrapping the 34-table schema once into a TEMPLATE database and
`CREATE DATABASE ... TEMPLATE ...` per test keeps per-test setup to a fast file-level copy.

Readable deterministic ids for fixtures live in `chorus.testing.uid`.
"""

from __future__ import annotations

import os
import shlex
import shutil
import socket
import subprocess
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

from chorus.ledger import Ledger

_PG_BIN = Path(os.environ.get("CHORUS_PG_BIN", "/opt/homebrew/opt/postgresql@18/bin"))
_TEMPLATE_DB = "chorus_template"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session", autouse=True)
def pg_conninfo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """A session-scoped throwaway PG18 cluster with the ledger schema baked into a template DB."""
    if not _PG_BIN.exists():
        pytest.skip(
            f"PostgreSQL 18 not found at {_PG_BIN} (set CHORUS_PG_BIN)", allow_module_level=False
        )
    data = tmp_path_factory.mktemp("chorus_pgdata")
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run(
        [
            str(_PG_BIN / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    port = _free_port()
    socket_dir = tmp_path_factory.mktemp("chorus_pgsock")
    socket_dirs = shlex.quote(str(socket_dir))
    subprocess.run(
        [
            str(_PG_BIN / "pg_ctl"),
            "-D",
            str(data),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1 -c fsync=off "
            f"-c unix_socket_directories={socket_dirs}",
            "-l",
            str(data / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    conninfo = f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    os.environ["CHORUS_TEST_PG"] = conninfo  # chorus.testing.open_test_ledger reads this
    import psycopg

    with psycopg.connect(conninfo, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {_TEMPLATE_DB}")
    Ledger.open(conninfo.replace("dbname=postgres", f"dbname={_TEMPLATE_DB}")).close()
    try:
        yield conninfo
    finally:
        subprocess.run(
            [str(_PG_BIN / "pg_ctl"), "-D", str(data), "-w", "stop"], capture_output=True, env=env
        )
        shutil.rmtree(data, ignore_errors=True)


_counter = {"n": 0}


@pytest.fixture
def pg_database(pg_conninfo: str) -> Iterator[str]:
    """A fresh template-copied database per test — its conninfo (schema + baseline pre-applied)."""
    import psycopg

    _counter["n"] += 1
    dbname = f"chorus_test_{_counter['n']}"
    with psycopg.connect(pg_conninfo, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {dbname} TEMPLATE {_TEMPLATE_DB}")
    try:
        yield pg_conninfo.replace("dbname=postgres", f"dbname={dbname}")
    finally:
        with psycopg.connect(pg_conninfo, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {dbname} WITH (FORCE)")


@pytest.fixture
def ledger(pg_database: str) -> Iterator[Ledger]:
    """A fresh, schema-ready ledger per test, scoped to one company."""
    store = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        yield store
    finally:
        store.close()
