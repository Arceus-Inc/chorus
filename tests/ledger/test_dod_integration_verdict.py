"""The typed delegation integration verdict survives storage and remains tenant scoped."""

from __future__ import annotations

import pytest

from chorus.ledger import DodStatus, IntegrationVerdict, Ledger, MergeReceipt, Task, load_migrations
from chorus.outcomes import Verifier
from chorus.testing import uid


def test_migration_follows_human_authorization_and_adds_typed_columns() -> None:
    migrations = load_migrations()
    migration = next(item for item in migrations if item.id == "0013_dod_integration_verdict")

    assert migrations.index(migration) > next(
        index
        for index, item in enumerate(migrations)
        if item.id == "0011_human_authorization_proof"
    )
    files_to_touch = next(
        (index for index, item in enumerate(migrations) if item.id == "0012_task_files_to_touch"),
        None,
    )
    if files_to_touch is not None:
        assert migrations.index(migration) > files_to_touch
    assert migration.statements() == [
        "ALTER TABLE dod\n    ADD COLUMN integration_ok boolean,\n    ADD COLUMN integration_note text"
    ]


def test_merge_receipt_rejects_non_boolean_merged_values() -> None:
    assert MergeReceipt.from_resource_ref(None) is None
    assert MergeReceipt.from_resource_ref({}) is None
    assert MergeReceipt.from_resource_ref({"merged": True}) == MergeReceipt(merged=True)
    with pytest.raises(ValueError, match="must be a boolean"):
        MergeReceipt.from_resource_ref({"merged": "false"})
    with pytest.raises(ValueError, match="must be a boolean"):
        MergeReceipt.from_resource_ref({"merged": 0})


def test_integration_verdict_survives_restart_and_is_hidden_by_rls(pg_database: str) -> None:
    import psycopg

    company_id = uid("integration-company")
    other_company_id = uid("other-integration-company")
    task_id = uid("integration-task")

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles "
            "WHERE rolname = 'chorus_integration_app') THEN CREATE ROLE chorus_integration_app "
            "LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_integration_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public "
            "TO chorus_integration_app"
        )
    app_conninfo = pg_database.replace("user=postgres", "user=chorus_integration_app")

    ledger = Ledger.open(app_conninfo, company_id=company_id)
    ledger.tasks.submit(Task(id=task_id, intent="integrate delegated release"))
    dod = ledger.dod.create(task_id, Verifier.command("pytest -q"))
    ledger.dod.record_verdict(
        dod.id,
        DodStatus.FAILED,
        integration=IntegrationVerdict(
            ok=False,
            note="primary child artifact reported resource_ref.merged=false",
        ),
    )
    ledger.close()

    restarted = Ledger.open(app_conninfo, company_id=company_id)
    persisted = restarted.dod.get_for_task(task_id)
    assert persisted is not None
    assert persisted.integration_ok is False
    assert persisted.integration_note == "primary child artifact reported resource_ref.merged=false"
    restarted.close()

    other_company = Ledger.open(app_conninfo, company_id=other_company_id)
    assert other_company.dod.get_for_task(task_id) is None
    other_company.close()
