"""Repos are dialect-neutral (spec 12 §3): no driver import, no engine-specific SQL.

The kernel's repos run unchanged on SQLite and Postgres; only the drivers (``_ledger.py`` /
``_migrations.py`` for SQLite, the Postgres driver) may speak a dialect. This source-scan guard
keeps it that way — same style as ``test_architecture_boundaries``.
"""

from __future__ import annotations

import re
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
    banned = (
        "rowid",
        "pragma",
        "json_extract",
        "json_each",
        " glob ",
        "ifnull",
        "group_concat",
        "strftime",
        "datetime(",
        "julianday",
        "insert or ",
        "replace into",
        "limit -1",
    )
    for construct in banned:
        assert construct not in source, f"{repo_file.name} uses {construct!r} — not portable"


_BOOLEAN_COLUMNS = (
    "active",
    "can_lead",
    "can_subdelegate",
    "is_primary",
    "hard_stop_enabled",
)
_BOOL_LITERAL = re.compile(rf"({'|'.join(_BOOLEAN_COLUMNS)})\s*(=|<>|!=)\s*[01]\b")


@pytest.mark.parametrize("repo_file", _REPO_FILES, ids=lambda p: p.name)
def test_repos_never_compare_boolean_columns_to_integer_literals(repo_file: Path) -> None:
    """SQLite stores flags as 0/1; Postgres as boolean. ``active = 1`` breaks on Postgres — the
    portable predicate is the bare boolean expression (``WHERE active``) or a bound parameter."""
    match = _BOOL_LITERAL.search(repo_file.read_text())
    assert match is None, f"{repo_file.name}: {match.group(0)!r} — compare booleans as booleans"
