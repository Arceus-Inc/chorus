"""Immutable, reproducible evaluation-run records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from chorus.ledger import (
    AgentConfigRevisionRef,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    EvalCase,
    EvalInputSnapshot,
    EvalOutputSnapshot,
    EvalRun,
    EvalRunStatus,
    EvalRunUsage,
    EvalSuite,
    Ledger,
    LedgerIntegrityError,
    Skill,
    SkillOrigin,
    SkillRevision,
    Task,
)
from chorus.testing import uid

_STARTED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 9, 12, 1, tzinfo=UTC)


def _suite(ledger: Ledger, *, suffix: str) -> tuple[EvalSuite, SkillRevision]:
    ledger.skills.insert(
        Skill(
            id=uid(f"run-skill-{suffix}"),
            employee_id="bex",
            slug=f"run-skill-{suffix}",
            name="Run skill",
            origin=SkillOrigin.CREATED,
        )
    )
    revision = ledger.skill_revisions.append(
        SkillRevision(
            id=uid(f"run-revision-{suffix}"),
            skill_id=uid(f"run-skill-{suffix}"),
            revision_no=1,
            action="create",
            file_inventory="[]",
            content_hash=suffix,
        )
    )
    case = ledger.eval_cases.create(
        EvalCase(
            id=uid(f"run-case-{suffix}"),
            skill_revision_id=revision.id,
            name="Case",
            input_text="Input",
            expected_behavior="Expected",
        )
    )
    return (
        ledger.eval_suites.create(
            EvalSuite(
                id=uid(f"run-suite-{suffix}"), skill_revision_id=revision.id, case_ids=(case.id,)
            )
        ),
        revision,
    )


def _artifact_revision(ledger: Ledger, *, suffix: str) -> ArtifactRevision:
    task = ledger.tasks.submit(Task(id=uid(f"run-task-{suffix}"), intent="evaluation evidence"))
    artifact = ledger.artifacts.create(
        Artifact(id=uid(f"run-artifact-{suffix}"), task_id=task.id, type=ArtifactType.DOC)
    )
    return ledger.artifact_revisions.record(
        ArtifactRevision(id=uid(f"run-artifact-revision-{suffix}"), artifact_id=artifact.id)
    )


def _run(
    suite: EvalSuite,
    revision: SkillRevision,
    *,
    artifact_revision_ids: tuple[str, ...] = (),
) -> EvalRun:
    return EvalRun(
        id=uid("eval-run"),
        eval_suite_id=suite.id,
        skill_revision_id=revision.id,
        agent_config_revision=AgentConfigRevisionRef("agent-config@42"),
        provider="anthropic",
        model="claude-sonnet",
        input_snapshot=EvalInputSnapshot("User input\n"),
        output_snapshot=EvalOutputSnapshot("Assistant output\n"),
        usage=EvalRunUsage(input_tokens=12, output_tokens=34, cost_usd=Decimal("0.005001")),
        artifact_revision_ids=artifact_revision_ids,
        status=EvalRunStatus.COMPLETED,
        started_at=_STARTED_AT,
        completed_at=_COMPLETED_AT,
    )


def test_eval_run_is_pinned_and_lists_in_creation_order(ledger: Ledger) -> None:
    suite, revision = _suite(ledger, suffix="one")
    evidence = _artifact_revision(ledger, suffix="one")
    second_evidence = _artifact_revision(ledger, suffix="two")
    created = ledger.eval_runs.create(
        _run(suite, revision, artifact_revision_ids=(second_evidence.id, evidence.id))
    )

    assert created.created_at is not None
    assert created.agent_config_revision == AgentConfigRevisionRef("agent-config@42")
    assert created.input_snapshot == EvalInputSnapshot("User input\n")
    assert created.output_snapshot == EvalOutputSnapshot("Assistant output\n")
    assert created.usage == EvalRunUsage(12, 34, Decimal("0.005001"))
    assert created.artifact_revision_ids == (second_evidence.id, evidence.id)
    assert ledger.eval_runs.get(created.id) == created
    assert ledger.eval_runs.list(suite.id) == [created]


def test_eval_run_rejects_invalid_usage_and_duplicate_artifacts() -> None:
    with pytest.raises(ValueError, match="nonnegative"):
        EvalRunUsage(input_tokens=-1, output_tokens=0, cost_usd=Decimal("0"))

    with pytest.raises(ValueError, match="duplicates"):
        EvalRun(
            id=uid("duplicate-eval-run"),
            eval_suite_id=uid("suite"),
            skill_revision_id=uid("revision"),
            agent_config_revision=AgentConfigRevisionRef("agent-config@42"),
            provider="provider",
            model="model",
            input_snapshot=EvalInputSnapshot("input"),
            output_snapshot=EvalOutputSnapshot("output"),
            usage=EvalRunUsage(0, 0, Decimal("0")),
            artifact_revision_ids=(uid("artifact-revision"), uid("artifact-revision")),
            status=EvalRunStatus.COMPLETED,
            started_at=_STARTED_AT,
            completed_at=_COMPLETED_AT,
        )


def test_eval_run_rejects_blank_identity_fields() -> None:
    cases = (
        ("id", "eval run id must not be blank"),
        ("eval_suite_id", "eval suite id must not be blank"),
        ("skill_revision_id", "skill revision id must not be blank"),
        ("provider", "provider must not be blank"),
        ("model", "model must not be blank"),
    )
    for field, message in cases:
        with pytest.raises(ValueError, match=message):
            EvalRun(
                id="  " if field == "id" else uid("validated-eval-run"),
                eval_suite_id="  " if field == "eval_suite_id" else uid("validated-suite"),
                skill_revision_id=(
                    "  " if field == "skill_revision_id" else uid("validated-revision")
                ),
                agent_config_revision=AgentConfigRevisionRef("agent-config@42"),
                provider="  " if field == "provider" else "provider",
                model="  " if field == "model" else "model",
                input_snapshot=EvalInputSnapshot("input"),
                output_snapshot=EvalOutputSnapshot("output"),
                usage=EvalRunUsage(0, 0, Decimal("0")),
                artifact_revision_ids=(),
                status=EvalRunStatus.COMPLETED,
                started_at=_STARTED_AT,
                completed_at=_COMPLETED_AT,
            )


def test_eval_run_rejects_blank_agent_config_and_artifact_revision_references() -> None:
    with pytest.raises(ValueError, match="agent config revision reference must not be blank"):
        AgentConfigRevisionRef("  ")

    with pytest.raises(ValueError, match="artifact revision ids must not be blank"):
        EvalRun(
            id=uid("blank-artifact-eval-run"),
            eval_suite_id=uid("suite"),
            skill_revision_id=uid("revision"),
            agent_config_revision=AgentConfigRevisionRef("agent-config@42"),
            provider="provider",
            model="model",
            input_snapshot=EvalInputSnapshot("input"),
            output_snapshot=EvalOutputSnapshot("output"),
            usage=EvalRunUsage(0, 0, Decimal("0")),
            artifact_revision_ids=("  ",),
            status=EvalRunStatus.COMPLETED,
            started_at=_STARTED_AT,
            completed_at=_COMPLETED_AT,
        )


def test_eval_run_rejects_reversed_terminal_timestamps() -> None:
    with pytest.raises(ValueError, match="must not precede"):
        EvalRun(
            id=uid("reversed-eval-run"),
            eval_suite_id=uid("suite"),
            skill_revision_id=uid("revision"),
            agent_config_revision=AgentConfigRevisionRef("agent-config@42"),
            provider="provider",
            model="model",
            input_snapshot=EvalInputSnapshot("input"),
            output_snapshot=EvalOutputSnapshot("output"),
            usage=EvalRunUsage(0, 0, Decimal("0")),
            artifact_revision_ids=(),
            status=EvalRunStatus.FAILED,
            started_at=_COMPLETED_AT,
            completed_at=_STARTED_AT,
        )


def test_eval_run_rejects_suite_revision_mismatch(ledger: Ledger) -> None:
    suite, _ = _suite(ledger, suffix="one")
    _, foreign_revision = _suite(ledger, suffix="two")

    with pytest.raises(LedgerIntegrityError):
        ledger.eval_runs.create(_run(suite, foreign_revision))

    assert ledger.eval_runs.get(uid("eval-run")) is None


def test_eval_run_rejects_artifacts_from_another_company(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_evidence = _artifact_revision(company_a, suffix="foreign")
        suite, revision = _suite(company_b, suffix="local")

        with pytest.raises(LedgerIntegrityError):
            company_b.eval_runs.create(
                _run(suite, revision, artifact_revision_ids=(foreign_evidence.id,))
            )

        foreign_suite, foreign_revision = _suite(company_a, suffix="foreign-suite")
        with pytest.raises(LedgerIntegrityError):
            company_b.eval_runs.create(_run(foreign_suite, foreign_revision))
    finally:
        company_b._conn.rollback()
        company_a.close()
        company_b.close()


def test_eval_run_evidence_is_append_only_for_the_runtime_role(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    ledger = Ledger.open(pg_database, company_id=company_id)
    try:
        suite, revision = _suite(ledger, suffix="append-only")
        evidence = _artifact_revision(ledger, suffix="append-only")
        run = ledger.eval_runs.create(_run(suite, revision, artifact_revision_ids=(evidence.id,)))
    finally:
        ledger.close()

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chorus_eval_app') "
            "THEN CREATE ROLE chorus_eval_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_eval_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON eval_run, eval_run_artifact_revision "
            "TO chorus_eval_app"
        )

    app_conninfo = pg_database.replace("user=postgres", "user=chorus_eval_app")
    with psycopg.connect(app_conninfo, autocommit=True) as app:
        app.execute("SELECT set_config('app.company_id', %s, false)", (company_id,))
        updated = app.execute(
            "UPDATE eval_run SET output_snapshot = 'rewritten' WHERE id = %s RETURNING id",
            (run.id,),
        ).fetchall()
        deleted_links = app.execute(
            "DELETE FROM eval_run_artifact_revision WHERE eval_run_id = %s RETURNING eval_run_id",
            (run.id,),
        ).fetchall()
        deleted_runs = app.execute(
            "DELETE FROM eval_run WHERE id = %s RETURNING id", (run.id,)
        ).fetchall()
        persisted = app.execute(
            "SELECT output_snapshot FROM eval_run WHERE id = %s", (run.id,)
        ).fetchone()
        persisted_links = app.execute(
            "SELECT artifact_revision_id FROM eval_run_artifact_revision WHERE eval_run_id = %s",
            (run.id,),
        ).fetchall()

    assert updated == []
    assert deleted_links == []
    assert deleted_runs == []
    assert persisted == ("Assistant output\n",)
    assert persisted_links == [(uuid.UUID(evidence.id),)]
