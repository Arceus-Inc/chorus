"""Repos are dialect-neutral (spec 12 §3): no driver import, no engine-specific SQL.

The kernel's repos run unchanged on SQLite and Postgres; only the drivers (``_ledger.py`` /
``_migrations.py`` for SQLite, the Postgres driver) may speak a dialect. This source-scan guard
keeps it that way — same style as ``test_architecture_boundaries``.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_REPOS = Path(str(files("chorus.ledger.repos")))
_REPO_FILES = sorted(p for p in _REPOS.glob("*.py") if p.name != "__init__.py")


@pytest.mark.parametrize("repo_file", _REPO_FILES, ids=lambda p: p.name)
def test_repos_do_not_import_a_db_driver(repo_file: Path) -> None:
    source = repo_file.read_text()
    for driver in ("sqlite3", "psycopg"):
        assert f"import {driver}" not in source and f"from {driver}" not in source, (
            f"{repo_file.name} imports {driver} — repos are typed against LedgerConnection"
        )


@pytest.mark.parametrize("repo_file", _REPO_FILES, ids=lambda p: p.name)
def test_repos_use_no_engine_specific_sql(repo_file: Path) -> None:
    # Coverage pragmas ("# pragma: no cover") are comments, not SQL — drop them before scanning.
    source = "\n".join(
        line.split("# pragma:", 1)[0] for line in repo_file.read_text().splitlines()
    ).lower()
    # rowid is SQLite's implicit physical id; Postgres has none. Insertion order must be explicit
    # data (a position column) or derived from time-ordered ids — never physical storage order.
    for construct in ("rowid", "pragma", "json_extract", "json_each", " glob "):
        assert construct not in source, f"{repo_file.name} uses {construct!r} — not portable"
