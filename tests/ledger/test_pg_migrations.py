"""The authored Postgres migration stream — applied-set deltas over the frozen baseline.

The baseline (``schema/*.sql``) bootstraps fresh databases; every later schema change is an
immutable ``migrations/NNNN_name.sql`` delta. ``Ledger.open`` applies pending deltas in id order
under the bootstrap advisory lock and records each in ``chorus_schema_migrations`` (id + checksum
+ applied_at — the applied-set model). It refuses to run when the database is *ahead* of the SDK
(an applied id the SDK does not ship) or when a shipped migration's checksum *drifted* (it was
edited after being applied somewhere). Fresh and migrated databases must converge on the same
schema.
"""

from __future__ import annotations

import uuid

import psycopg
import pytest

from chorus.ledger import Ledger, baseline
from chorus.ledger._migrations import (
    LedgerAheadError,
    Migration,
    MigrationDriftError,
    load_migrations,
)
from chorus.ledger._migrations import (
    load_migrations as _real_load,
)

pytestmark = pytest.mark.integration

_FIXTURE = Migration(
    id="0099_widget",
    sql=(  # checksum derives from these bytes in __post_init__
        "CREATE TABLE widget (\n"
        "    company_id uuid NOT NULL DEFAULT "
        "(NULLIF(current_setting('app.company_id', true), ''))::uuid,\n"
        "    id uuid PRIMARY KEY,\n"
        "    name text NOT NULL,\n"
        "    created_at timestamptz NOT NULL DEFAULT now()\n"
        ");\n"
        "ALTER TABLE widget ENABLE ROW LEVEL SECURITY;\n"
        "ALTER TABLE widget FORCE ROW LEVEL SECURITY;\n"
        "CREATE POLICY widget_company_isolation ON widget USING (company_id = "
        "(SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid)) "
        "WITH CHECK (company_id = "
        "(SELECT (NULLIF(current_setting('app.company_id', true), ''))::uuid));\n"
        "CREATE INDEX widget_name_idx ON widget(company_id, name)"
    ),
)


def _applied_rows(conninfo: str) -> dict[str, str]:
    with psycopg.connect(conninfo) as db:
        rows = db.execute("SELECT id, checksum FROM chorus_schema_migrations").fetchall()
    return {row[0]: row[1] for row in rows}


def _table_exists(conninfo: str, table: str) -> bool:
    with psycopg.connect(conninfo) as db:
        return db.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is not None


def test_migration_reports_the_tables_it_creates() -> None:
    """Deployments grant their runtime role per migration — the table list comes from the SQL."""
    assert _FIXTURE.table_names() == ["widget"]
    skills = next(m for m in load_migrations() if m.id == "0002_skills")
    assert skills.table_names() == ["skill", "skill_revision"]
    eval_cases = next(m for m in load_migrations() if m.id == "0006_eval_cases")
    assert eval_cases.table_names() == ["eval_case"]
    eval_suites = next(m for m in load_migrations() if m.id == "0007_eval_suites")
    assert eval_suites.table_names() == ["eval_suite", "eval_suite_case"]
    human_auth = next(m for m in load_migrations() if m.id == "0011_human_authorization_proof")
    assert human_auth.table_names() == ["human_authorization_proof"]
    assert "CONSTRAINT TRIGGER approval_authorization_requires_terminal_proof" in human_auth.sql
    assert "DEFERRABLE INITIALLY DEFERRED" in human_auth.sql


def test_shipped_migrations_load_in_id_order() -> None:
    """The real shipped stream loads cleanly, id-ordered (0002_skills is the first delta)."""
    shipped = load_migrations()
    ids = [m.id for m in shipped]
    assert ids == sorted(ids)
    assert "0002_skills" in set(ids)
    assert "0011_human_authorization_proof" in set(ids)
    assert ids.index("0010_agent_config_revisions") < ids.index("0011_human_authorization_proof")
    assert "0012_task_files_to_touch" in set(ids)
    assert ids.index("0011_human_authorization_proof") < ids.index("0012_task_files_to_touch")
    assert "0006_human_authorization_proof" not in set(ids)


def test_split_statements_keeps_dollar_quoted_function_bodies_intact() -> None:
    """Plpgsql trigger bodies contain semicolons and must stay one statement."""
    from chorus.ledger._migrations import split_statements

    sql = """
    CREATE FUNCTION foo() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'human authorization proof is immutable';
    END;
    $$;
    CREATE TABLE bar (id uuid);
    """
    statements = split_statements(sql)
    assert len(statements) == 2
    assert "RAISE EXCEPTION" in statements[0]
    assert ";" in statements[0]
    assert statements[1].startswith("CREATE TABLE")


def test_agent_session_migration_reports_tables() -> None:
    """0005_agent_session creates the handle table and nothing else.

    No ``conversation_message`` / ``tool_call``: dream owns the transcript, and
    a second copy here would only ever be the stale one.
    """
    migration = next(m for m in load_migrations() if m.id == "0005_agent_session")
    assert migration.table_names() == ["agent_session"]


def test_run_carryover_ownership_is_derived_from_run_schema(pg_database: str) -> None:
    """Carryovers cannot name a different task than their foreign-keyed run."""
    migration = next(m for m in load_migrations() if m.id == "0006_run_carryover")
    create_table = next(statement for statement in migration.statements() if statement.startswith("CREATE TABLE"))
    assert "task_id" not in create_table
    with psycopg.connect(pg_database) as db:
        columns = {
            row[0]
            for row in db.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name = 'run_carryover'"
            ).fetchall()
        }
        indexes = {
            row[0]
            for row in db.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'run'").fetchall()
        }
    assert "task_id" not in columns
    assert "run_task_created_idx" in indexes


def test_fresh_bootstrap_applies_baseline_then_all_migrations(
    pg_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    import chorus.ledger._ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    store = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    store.close()
    assert _table_exists(pg_database, "widget")
    applied = _applied_rows(pg_database)
    assert "0001_baseline" in applied
    assert applied["0099_widget"] == _FIXTURE.checksum


def test_existing_database_applies_only_pending_migrations(
    pg_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database baselined before the migration existed gets exactly the delta on reopen."""
    import chorus.ledger._ledger as ledger_mod

    assert not _table_exists(pg_database, "widget")  # template predates the fixture
    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    store = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    store.close()
    assert _table_exists(pg_database, "widget")
    assert _applied_rows(pg_database)["0099_widget"] == _FIXTURE.checksum


def test_origin_main_baseline_upgrades_files_to_touch(
    pg_database: str,
) -> None:
    """A database already at current main (through 0011) applies the additive scope migration."""
    baseline_id, checksum, statements = baseline()

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
        admin.execute(
            "CREATE TABLE chorus_schema_migrations ("
            "id text PRIMARY KEY, checksum text NOT NULL, applied_at timestamptz NOT NULL)"
        )
        for statement in statements:
            admin.execute(statement)
        admin.execute(
            "INSERT INTO chorus_schema_migrations (id, checksum, applied_at) VALUES (%s, %s, now())",
            (baseline_id, checksum),
        )
        for migration in load_migrations():
            if migration.id == "0012_task_files_to_touch":
                continue
            for statement in migration.statements():
                admin.execute(statement)
            admin.execute(
                "INSERT INTO chorus_schema_migrations (id, checksum, applied_at) VALUES (%s, %s, now())",
                (migration.id, migration.checksum),
            )

    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()
    with psycopg.connect(pg_database) as admin:
        column = admin.execute(
            "SELECT data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'task' AND column_name = 'files_to_touch'"
        ).fetchone()
    assert column == ("ARRAY",)
    assert "0012_task_files_to_touch" in _applied_rows(pg_database)


def test_reapply_is_a_noop(pg_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import chorus.ledger._ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()
    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()  # second open: already applied
    assert _table_exists(pg_database, "widget")


def test_database_ahead_of_sdk_is_refused(
    pg_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An applied id the SDK does not ship means the SDK is stale — upgrade it, never guess."""
    import chorus.ledger._ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()
    monkeypatch.setattr(ledger_mod, "load_migrations", _real_load)
    with pytest.raises(LedgerAheadError, match="0099_widget"):
        Ledger.open(pg_database, company_id=str(uuid.uuid4()))


def test_edited_migration_is_refused(pg_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Deployed migrations are immutable — a checksum mismatch is drift, not a retry."""
    import chorus.ledger._ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()
    edited = Migration(id="0099_widget", sql="SELECT 1")
    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), edited])
    with pytest.raises(MigrationDriftError, match="0099_widget"):
        Ledger.open(pg_database, company_id=str(uuid.uuid4()))


def test_migrated_and_fresh_databases_converge(
    pg_conninfo: str, pg_database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The parity invariant: baseline+delta (migrated) == baseline+delta (fresh) — same columns,
    same indexes, same RLS posture on the migration-created table."""
    import chorus.ledger._ledger as ledger_mod

    monkeypatch.setattr(ledger_mod, "load_migrations", lambda: [*_real_load(), _FIXTURE])
    Ledger.open(pg_database, company_id=str(uuid.uuid4())).close()  # migrated path

    fresh_db = f"chorus_mig_fresh_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(pg_conninfo, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {fresh_db}")
    fresh = pg_database.rsplit("dbname=", 1)[0] + f"dbname={fresh_db}"
    try:
        Ledger.open(fresh, company_id=str(uuid.uuid4())).close()  # fresh path

        def describe(conninfo: str) -> tuple[list[tuple[str, str]], set[str], bool]:
            with psycopg.connect(conninfo) as db:
                columns = db.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_name = 'widget' ORDER BY ordinal_position"
                ).fetchall()
                indexes = {
                    row[0]
                    for row in db.execute(
                        "SELECT indexname FROM pg_indexes WHERE tablename = 'widget'"
                    ).fetchall()
                }
                forced = db.execute(
                    "SELECT relforcerowsecurity FROM pg_class WHERE relname = 'widget'"
                ).fetchone()[0]
            return columns, indexes, forced

        assert describe(pg_database) == describe(fresh)
        assert describe(fresh)[2] is True  # FORCE RLS held on both paths
    finally:
        with psycopg.connect(pg_conninfo, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE IF EXISTS {fresh_db}")
