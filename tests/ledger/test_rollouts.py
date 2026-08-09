"""Immutable rollout candidates and their gated promotion decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from chorus.ledger import (
    AgentConfigRevision,
    AgentConfigRevisionRef,
    AgentIdentity,
    AgentsMdReference,
    Approval,
    ApprovalAction,
    ApprovalSubjectKind,
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
    PromotionGates,
    ProviderModelConfig,
    ReplayRegression,
    Rollout,
    RolloutDecision,
    RolloutStage,
    RolloutStatus,
    SandboxProfile,
    Skill,
    SkillOrigin,
    SkillRevision,
    Task,
)
from chorus.testing import uid

_STARTED_AT = datetime(2026, 8, 9, 12, 0, tzinfo=UTC)
_COMPLETED_AT = datetime(2026, 8, 9, 12, 1, tzinfo=UTC)


def _suite(ledger: Ledger, suffix: str) -> tuple[EvalSuite, SkillRevision]:
    skill = ledger.skills.insert(
        Skill(
            id=uid(f"rollout-skill-{suffix}"),
            employee_id="bex",
            slug=f"rollout-skill-{suffix}",
            name="Rollout skill",
            origin=SkillOrigin.CREATED,
        )
    )
    revision = ledger.skill_revisions.append(
        SkillRevision(
            id=uid(f"rollout-revision-{suffix}"),
            skill_id=skill.id,
            revision_no=1,
            action="create",
            file_inventory="[]",
            content_hash=suffix,
        )
    )
    case = ledger.eval_cases.create(
        EvalCase(
            id=uid(f"rollout-case-{suffix}"),
            skill_revision_id=revision.id,
            name="Promotion check",
            input_text="Input",
            expected_behavior="Expected",
        )
    )
    return (
        ledger.eval_suites.create(
            EvalSuite(
                id=uid(f"rollout-suite-{suffix}"),
                skill_revision_id=revision.id,
                case_ids=(case.id,),
            )
        ),
        revision,
    )


def _artifact_revision(ledger: Ledger, suffix: str) -> ArtifactRevision:
    task = ledger.tasks.submit(Task(id=uid(f"rollout-task-{suffix}"), intent="eval evidence"))
    artifact = ledger.artifacts.create(
        Artifact(id=uid(f"rollout-artifact-{suffix}"), task_id=task.id, type=ArtifactType.DOC)
    )
    return ledger.artifact_revisions.record(
        ArtifactRevision(id=uid(f"rollout-artifact-revision-{suffix}"), artifact_id=artifact.id)
    )


def _rollout(ledger: Ledger, suffix: str) -> Rollout:
    suite, revision = _suite(ledger, suffix)
    evidence = _artifact_revision(ledger, suffix)
    agent_config = ledger.agent_config_revisions.create(
        AgentConfigRevision(
            id=uid(f"rollout-agent-config-{suffix}"),
            agent=AgentIdentity(f"rollout-agent-{suffix}"),
            revision_no=1,
            agents_md=AgentsMdReference("agents-md@1", "instructions"),
            provider_model=ProviderModelConfig("anthropic", "claude-sonnet"),
            sandbox_profile=SandboxProfile("workspace-write"),
        )
    )
    run = ledger.eval_runs.create(
        EvalRun(
            id=uid(f"rollout-run-{suffix}"),
            eval_suite_id=suite.id,
            skill_revision_id=revision.id,
            agent_config_revision=AgentConfigRevisionRef(agent_config.id),
            provider="anthropic",
            model="claude-sonnet",
            input_snapshot=EvalInputSnapshot("Input"),
            output_snapshot=EvalOutputSnapshot("Output"),
            usage=EvalRunUsage(12, 34, Decimal("0.005")),
            artifact_revision_ids=(evidence.id,),
            status=EvalRunStatus.COMPLETED,
            started_at=_STARTED_AT,
            completed_at=_COMPLETED_AT,
        )
    )
    return Rollout(
        id=uid(f"rollout-{suffix}"),
        skill_revision_id=revision.id,
        eval_suite_id=suite.id,
        eval_run_id=run.id,
        evidence_artifact_revision_ids=(evidence.id,),
    )


def _approved_gates(ledger: Ledger, rollout: Rollout, suffix: str) -> PromotionGates:
    approval_id = uid(f"rollout-approval-{suffix}")
    reviewer_id = uid(f"rollout-reviewer-{suffix}")
    ledger.approvals.request(
        Approval(
            id=approval_id,
            subject_kind=ApprovalSubjectKind.ROLLOUT,
            subject_id=rollout.id,
            reason="reviewed rollout evidence",
            action=ApprovalAction.PROMOTE_ROLLOUT,
        )
    )
    ledger.approvals.approve(approval_id, decided_by_user_id=reviewer_id)
    return PromotionGates(
        approval_id=approval_id,
        reviewer_user_id=reviewer_id,
        replay_regression=ReplayRegression.NONE,
    )


def _canary_decision(rollout: Rollout, suffix: str) -> RolloutDecision:
    return RolloutDecision(
        id=uid(f"rollout-canary-{suffix}"),
        rollout_id=rollout.id,
        stage=RolloutStage.CANARY,
        status=RolloutStatus.COMPLETED,
    )


def _full_decision(rollout: Rollout, gates: PromotionGates, suffix: str) -> RolloutDecision:
    return RolloutDecision(
        id=uid(f"rollout-full-{suffix}"),
        rollout_id=rollout.id,
        stage=RolloutStage.FULL,
        status=RolloutStatus.PROMOTED,
        gates=gates,
    )


def test_rollout_pins_evidence_and_records_a_gated_full_promotion(ledger: Ledger) -> None:
    rollout = ledger.rollouts.create(_rollout(ledger, "one"))
    gates = _approved_gates(ledger, rollout, "one")

    canary = ledger.rollouts.record_decision(_canary_decision(rollout, "one"))
    full = ledger.rollouts.record_decision(_full_decision(rollout, gates, "one"))

    assert ledger.rollouts.get(rollout.id) == rollout
    assert ledger.rollouts.decisions(rollout.id) == [canary, full]
    assert full.gates == gates


def test_rollout_models_reject_invalid_evidence_and_stage_combinations() -> None:
    with pytest.raises(
        ValueError, match="rollout evidence artifact revision ids must not be empty"
    ):
        Rollout(
            id=uid("invalid-rollout"),
            skill_revision_id=uid("revision"),
            eval_suite_id=uid("suite"),
            eval_run_id=uid("run"),
            evidence_artifact_revision_ids=(),
        )

    with pytest.raises(ValueError, match="canary rollout decision must be completed without gates"):
        RolloutDecision(
            id=uid("invalid-canary"),
            rollout_id=uid("rollout"),
            stage=RolloutStage.CANARY,
            status=RolloutStatus.PROMOTED,
        )

    with pytest.raises(ValueError, match="full rollout decision must be promoted with gates"):
        RolloutDecision(
            id=uid("invalid-full"),
            rollout_id=uid("rollout"),
            stage=RolloutStage.FULL,
            status=RolloutStatus.PROMOTED,
        )


def test_full_promotion_rejects_missing_canary_or_critical_regression(ledger: Ledger) -> None:
    rollout = ledger.rollouts.create(_rollout(ledger, "gates"))
    gates = _approved_gates(ledger, rollout, "gates")

    with pytest.raises(ValueError, match="full promotion requires a completed canary"):
        ledger.rollouts.record_decision(_full_decision(rollout, gates, "gates"))

    ledger.rollouts.record_decision(_canary_decision(rollout, "gates"))
    blocked_gates = PromotionGates(
        approval_id=gates.approval_id,
        reviewer_user_id=gates.reviewer_user_id,
        replay_regression=ReplayRegression.CRITICAL,
    )
    with pytest.raises(ValueError, match="critical replay regression blocks full promotion"):
        ledger.rollouts.record_decision(_full_decision(rollout, blocked_gates, "blocked"))


def test_full_promotion_requires_approved_matching_rollout_reviewer(ledger: Ledger) -> None:
    rollout = ledger.rollouts.create(_rollout(ledger, "approval"))
    ledger.rollouts.record_decision(_canary_decision(rollout, "approval"))
    approval_id = uid("rollout-approval-pending")
    ledger.approvals.request(
        Approval(
            id=approval_id,
            subject_kind=ApprovalSubjectKind.ROLLOUT,
            subject_id=rollout.id,
            reason="awaiting reviewer",
            action=ApprovalAction.PROMOTE_ROLLOUT,
        )
    )
    gates = PromotionGates(
        approval_id=approval_id,
        reviewer_user_id=uid("rollout-reviewer-pending"),
        replay_regression=ReplayRegression.NONE,
    )

    with pytest.raises(ValueError, match="full promotion requires an approved rollout approval"):
        ledger.rollouts.record_decision(_full_decision(rollout, gates, "approval"))

    ledger.approvals.approve(approval_id, decided_by_user_id=uid("rollout-reviewer-approved"))
    mismatched_gates = PromotionGates(
        approval_id=approval_id,
        reviewer_user_id=uid("rollout-reviewer-mismatched"),
        replay_regression=ReplayRegression.NONE,
    )
    with pytest.raises(ValueError, match="full promotion requires an approved rollout approval"):
        ledger.rollouts.record_decision(_full_decision(rollout, mismatched_gates, "mismatched"))


def test_rollout_evidence_must_belong_to_its_pinned_eval_run(ledger: Ledger) -> None:
    candidate = _rollout(ledger, "provenance")
    unrelated_evidence = _artifact_revision(ledger, "unrelated")

    with pytest.raises(LedgerIntegrityError):
        ledger.rollouts.create(
            Rollout(
                id=candidate.id,
                skill_revision_id=candidate.skill_revision_id,
                eval_suite_id=candidate.eval_suite_id,
                eval_run_id=candidate.eval_run_id,
                evidence_artifact_revision_ids=(unrelated_evidence.id,),
            )
        )


def test_rollout_rejects_repeated_stage_and_cross_tenant_evidence(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        local = company_a.rollouts.create(_rollout(company_a, "local"))
        company_a.rollouts.record_decision(_canary_decision(local, "local"))
        with pytest.raises(ValueError, match="rollout stage has already been decided"):
            company_a.rollouts.record_decision(_canary_decision(local, "repeated"))

        foreign = _rollout(company_a, "foreign")
        with pytest.raises(LedgerIntegrityError):
            company_b.rollouts.create(foreign)
    finally:
        company_a.close()
        company_b.close()


def test_rollout_records_are_append_only_for_the_runtime_role(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    ledger = Ledger.open(pg_database, company_id=company_id)
    try:
        rollout = ledger.rollouts.create(_rollout(ledger, "append-only"))
        canary = ledger.rollouts.record_decision(_canary_decision(rollout, "append-only"))
    finally:
        ledger.close()

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chorus_rollout_app') "
            "THEN CREATE ROLE chorus_rollout_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_rollout_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON rollout, rollout_evidence, rollout_decision "
            "TO chorus_rollout_app"
        )

    app_conninfo = pg_database.replace("user=postgres", "user=chorus_rollout_app")
    with psycopg.connect(app_conninfo, autocommit=True) as app:
        app.execute("SELECT set_config('app.company_id', %s, false)", (company_id,))
        updated = app.execute(
            "UPDATE rollout_decision SET status = 'promoted' WHERE id = %s RETURNING id",
            (canary.id,),
        ).fetchall()
        deleted_evidence = app.execute(
            "DELETE FROM rollout_evidence WHERE rollout_id = %s RETURNING rollout_id",
            (rollout.id,),
        ).fetchall()
        deleted_rollouts = app.execute(
            "DELETE FROM rollout WHERE id = %s RETURNING id", (rollout.id,)
        ).fetchall()
        persisted_decision = app.execute(
            "SELECT status FROM rollout_decision WHERE id = %s", (canary.id,)
        ).fetchone()
        evidence_count = app.execute(
            "SELECT COUNT(*) FROM rollout_evidence WHERE rollout_id = %s", (rollout.id,)
        ).fetchone()

    assert updated == []
    assert deleted_evidence == []
    assert deleted_rollouts == []
    assert persisted_decision == ("completed",)
    assert evidence_count == (1,)
