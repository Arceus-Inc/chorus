"""Reviewable, proposal-only Reflection Coach artifacts."""

from __future__ import annotations

import uuid

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Ledger,
    LedgerIntegrityError,
    ReflectionProposal,
    ReflectionProposalTarget,
    ReflectionTargetKind,
    Routine,
    RoutineRun,
    RoutineTrigger,
    Run,
    RunStatus,
    Task,
    TrajectoryRef,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _source(
    ledger: Ledger,
    suffix: str,
    *,
    employee_id: str = "reflection-coach",
    role: str = "reflection_coach",
    run_status: RunStatus = RunStatus.SUCCEEDED,
    complete_routine_run: bool = True,
) -> tuple[str, str, str]:
    ledger.employees.create(Employee(id=employee_id, name="Reflection Coach", role=role))
    task = ledger.tasks.submit(
        Task(id=uid(f"proposal-task-{suffix}"), intent="review recent trajectories")
    )
    routine = ledger.routines.create(
        Routine(
            id=uid(f"proposal-routine-{suffix}"),
            employee_id=employee_id,
            intent_template="proposal-only reflection",
        )
    )
    trigger = ledger.routine_triggers.create(
        RoutineTrigger(id=uid(f"proposal-trigger-{suffix}"), routine_id=routine.id)
    )
    routine_run = ledger.routine_runs.record(
        RoutineRun(
            id=uid(f"proposal-routine-run-{suffix}"),
            routine_id=routine.id,
            trigger_id=trigger.id,
        )
    )
    ledger.routine_runs.dispatch(routine_run.id, linked_task_id=task.id)
    if complete_routine_run:
        ledger.routine_runs.complete(routine_run.id)
    run = ledger.runs.create(
        Run(
            id=uid(f"proposal-run-{suffix}"),
            employee_id=employee_id,
            task_id=task.id,
            status=run_status,
        )
    )
    return employee_id, routine_run.id, run.id


def _evidence(ledger: Ledger, suffix: str) -> str:
    task = ledger.tasks.submit(Task(id=uid(f"evidence-task-{suffix}"), intent="trajectory"))
    artifact = ledger.artifacts.create(
        Artifact(id=uid(f"evidence-artifact-{suffix}"), task_id=task.id, type=ArtifactType.FINDING)
    )
    return ledger.artifact_revisions.record(
        ArtifactRevision(id=uid(f"evidence-revision-{suffix}"), artifact_id=artifact.id)
    ).id


def _trajectory(ledger: Ledger, suffix: str) -> TrajectoryRef:
    employee_id = f"trajectory-agent-{suffix}"
    ledger.employees.create(Employee(id=employee_id, name="Trajectory Agent", role="engineer"))
    task = ledger.tasks.submit(Task(id=uid(f"trajectory-task-{suffix}"), intent="trajectory"))
    run = ledger.runs.create(
        Run(
            id=uid(f"trajectory-run-{suffix}"),
            employee_id=employee_id,
            task_id=task.id,
            status=RunStatus.SUCCEEDED,
        )
    )
    return TrajectoryRef(run_id=run.id, task_id=task.id)


def _target(ledger: Ledger, suffix: str, *, owner_employee_id: str | None = None) -> ReflectionProposalTarget:
    owner_id = owner_employee_id or f"target-agent-{suffix}"
    if owner_employee_id is None:
        ledger.employees.create(Employee(id=owner_id, name="Target Agent", role="engineer"))
    return ReflectionProposalTarget(
        kind=ReflectionTargetKind.SKILL,
        owner_employee_id=owner_id,
        target_id="backend-engineer/test-evidence",
        target_revision="skill@4",
    )


def _proposal(
    *,
    suffix: str,
    employee_id: str,
    routine_run_id: str,
    run_id: str,
    target: ReflectionProposalTarget,
    trajectory_refs: tuple[TrajectoryRef, ...],
    evidence_ids: tuple[str, ...],
) -> ReflectionProposal:
    return ReflectionProposal(
        artifact_id=uid(f"proposal-artifact-{suffix}"),
        artifact_revision_id=uid(f"proposal-revision-{suffix}"),
        target=target,
        diff="--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1,2 +1,3 @@\n existing\n+require replay evidence\n",
        rationale="Repeated trajectories omit replay evidence, so make it explicit.",
        trajectory_refs=trajectory_refs,
        evidence_artifact_revision_ids=evidence_ids,
        source_routine_run_id=routine_run_id,
        source_run_id=run_id,
        source_employee_id=employee_id,
    )


def test_completed_reflection_run_lands_a_discoverable_immutable_proposal(ledger: Ledger) -> None:
    employee_id, routine_run_id, run_id = _source(ledger, "one")
    target = _target(ledger, "one")
    proposal = _proposal(
        suffix="one",
        employee_id=employee_id,
        routine_run_id=routine_run_id,
        run_id=run_id,
        target=target,
        trajectory_refs=(_trajectory(ledger, "one"), _trajectory(ledger, "two")),
        evidence_ids=(_evidence(ledger, "one"), _evidence(ledger, "two")),
    )

    recorded = ledger.reflection_proposals.create(proposal)

    assert recorded.artifact_revision_id == proposal.artifact_revision_id
    assert recorded.created_at is not None
    assert recorded.trajectory_refs == proposal.trajectory_refs
    assert ledger.reflection_proposals.get(proposal.artifact_revision_id) == recorded
    assert ledger.reflection_proposals.by_target(proposal.target) == [recorded]
    artifact = ledger.artifacts.get(proposal.artifact_id)
    revision = ledger.artifact_revisions.get(proposal.artifact_revision_id)
    assert artifact is not None and artifact.type is ArtifactType.ARTIFACT
    assert artifact.provider == "reflection_coach"
    assert artifact.review_state == "proposed"
    assert revision is not None and revision.created_by_run_id == run_id


@pytest.mark.parametrize(
    ("diff", "message"),
    (
        ("", "diff must not be empty"),
        ("replace it", "diff must be a unified patch"),
    ),
)
def test_proposal_rejects_empty_or_malformed_diffs(diff: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ReflectionProposal(
            artifact_id=uid("invalid-artifact"),
            artifact_revision_id=uid("invalid-revision"),
            target=ReflectionProposalTarget(
                ReflectionTargetKind.AGENTS_MD, "target-agent", "AGENTS.md", "main"
            ),
            diff=diff,
            rationale="Reasoned from evidence.",
            trajectory_refs=(
                TrajectoryRef(uid("trajectory-run-one"), uid("trajectory-task-one")),
                TrajectoryRef(uid("trajectory-run-two"), uid("trajectory-task-two")),
            ),
            evidence_artifact_revision_ids=(uid("evidence-one"), uid("evidence-two")),
            source_routine_run_id=uid("routine-run"),
            source_run_id=uid("run"),
            source_employee_id="reflection-coach",
        )


def test_proposal_rejects_blank_ids_and_insufficient_or_duplicate_trajectory_refs() -> None:
    target = ReflectionProposalTarget(
        ReflectionTargetKind.TOOL_DESCRIPTION, "target-agent", "repo_search", "v1"
    )
    with pytest.raises(ValueError, match="artifact id must not be blank"):
        ReflectionProposal(
            artifact_id=" ",
            artifact_revision_id=uid("revision"),
            target=target,
            diff="--- a/tool\n+++ b/tool\n@@ -1 +1 @@\n-old\n+new\n",
            rationale="Reasoned from evidence.",
            trajectory_refs=(
                TrajectoryRef(uid("trajectory-run-one"), uid("trajectory-task-one")),
                TrajectoryRef(uid("trajectory-run-two"), uid("trajectory-task-two")),
            ),
            evidence_artifact_revision_ids=(uid("one"), uid("two")),
            source_routine_run_id=uid("routine-run"),
            source_run_id=uid("run"),
            source_employee_id="reflection-coach",
        )
    for trajectory_refs, message in (
        ((TrajectoryRef(uid("run-one"), uid("task-one")),), "at least two"),
        (
            (
                TrajectoryRef(uid("run-one"), uid("task-one")),
                TrajectoryRef(uid("run-one"), uid("task-one")),
            ),
            "duplicates",
        ),
    ):
        with pytest.raises(ValueError, match=message):
            ReflectionProposal(
                artifact_id=uid("artifact"),
                artifact_revision_id=uid("revision"),
                target=target,
                diff="--- a/tool\n+++ b/tool\n@@ -1 +1 @@\n-old\n+new\n",
                rationale="Reasoned from evidence.",
                trajectory_refs=trajectory_refs,
                evidence_artifact_revision_ids=(uid("evidence"),),
                source_routine_run_id=uid("routine-run"),
                source_run_id=uid("run"),
                source_employee_id="reflection-coach",
            )


def test_evidence_cannot_stand_in_for_distinct_trajectory_refs() -> None:
    target = ReflectionProposalTarget(
        ReflectionTargetKind.TOOL_DESCRIPTION, "target-agent", "repo_search", "v1"
    )
    with pytest.raises(ValueError, match="at least two distinct trajectory"):
        ReflectionProposal(
            artifact_id=uid("artifact"),
            artifact_revision_id=uid("revision"),
            target=target,
            diff="--- a/tool\n+++ b/tool\n@@ -1 +1 @@\n-old\n+new\n",
            rationale="Reasoned from evidence.",
            trajectory_refs=(TrajectoryRef(uid("run-one"), uid("task-one")),),
            evidence_artifact_revision_ids=tuple(uid(f"evidence-{index}") for index in range(3)),
            source_routine_run_id=uid("routine-run"),
            source_run_id=uid("run"),
            source_employee_id="reflection-coach",
        )


def test_proposal_rejects_self_target() -> None:
    with pytest.raises(ValueError, match="must not target its source employee"):
        ReflectionProposal(
            artifact_id=uid("artifact"),
            artifact_revision_id=uid("revision"),
            target=ReflectionProposalTarget(
                ReflectionTargetKind.SKILL,
                "reflection-coach",
                "backend-engineer/test-evidence",
                "skill@4",
            ),
            diff="--- a/tool\n+++ b/tool\n@@ -1 +1 @@\n-old\n+new\n",
            rationale="Reasoned from evidence.",
            trajectory_refs=(
                TrajectoryRef(uid("run-one"), uid("task-one")),
                TrajectoryRef(uid("run-two"), uid("task-two")),
            ),
            evidence_artifact_revision_ids=(uid("evidence"),),
            source_routine_run_id=uid("routine-run"),
            source_run_id=uid("run"),
            source_employee_id="reflection-coach",
        )


def test_proposal_rejects_cross_tenant_evidence(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_evidence = _evidence(company_a, "foreign")
        employee_id, routine_run_id, run_id = _source(company_b, "local")
        proposal = _proposal(
            suffix="local",
            employee_id=employee_id,
            routine_run_id=routine_run_id,
            run_id=run_id,
            target=_target(company_b, "local"),
            trajectory_refs=(_trajectory(company_b, "local"), _trajectory(company_b, "two")),
            evidence_ids=(_evidence(company_b, "local"), foreign_evidence),
        )

        with pytest.raises(LedgerIntegrityError):
            company_b.reflection_proposals.create(proposal)

        assert company_b.artifacts.get(proposal.artifact_id) is None
    finally:
        company_b.close()
        company_a.close()


def test_proposal_rejects_cross_tenant_trajectory_ref(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        foreign_trajectory = _trajectory(company_a, "foreign")
        employee_id, routine_run_id, run_id = _source(company_b, "local")
        proposal = _proposal(
            suffix="local",
            employee_id=employee_id,
            routine_run_id=routine_run_id,
            run_id=run_id,
            target=_target(company_b, "local"),
            trajectory_refs=(_trajectory(company_b, "local"), foreign_trajectory),
            evidence_ids=(_evidence(company_b, "local"),),
        )

        with pytest.raises(LedgerIntegrityError):
            company_b.reflection_proposals.create(proposal)

        assert company_b.artifacts.get(proposal.artifact_id) is None
    finally:
        company_b.close()
        company_a.close()


def test_proposal_rejects_wrong_source_role_or_routine(ledger: Ledger) -> None:
    employee_id, routine_run_id, run_id = _source(
        ledger, "wrong-role", employee_id="ordinary-agent", role="engineer"
    )
    proposal = _proposal(
        suffix="wrong-role",
        employee_id=employee_id,
        routine_run_id=routine_run_id,
        run_id=run_id,
        target=_target(ledger, "wrong-role"),
        trajectory_refs=(_trajectory(ledger, "one"), _trajectory(ledger, "two")),
        evidence_ids=(_evidence(ledger, "one"),),
    )

    with pytest.raises(ValueError, match="Reflection Coach"):
        ledger.reflection_proposals.create(proposal)


def test_proposal_rejects_non_succeeded_source_or_incomplete_routine(ledger: Ledger) -> None:
    employee_id, routine_run_id, run_id = _source(
        ledger, "failed", employee_id="failed-reflection-coach", run_status=RunStatus.FAILED
    )
    failed_source = _proposal(
        suffix="failed",
        employee_id=employee_id,
        routine_run_id=routine_run_id,
        run_id=run_id,
        target=_target(ledger, "failed"),
        trajectory_refs=(_trajectory(ledger, "one"), _trajectory(ledger, "two")),
        evidence_ids=(_evidence(ledger, "one"),),
    )
    with pytest.raises(ValueError, match="succeeded"):
        ledger.reflection_proposals.create(failed_source)

    employee_id, routine_run_id, run_id = _source(
        ledger,
        "incomplete",
        employee_id="incomplete-reflection-coach",
        complete_routine_run=False,
    )
    incomplete_routine = _proposal(
        suffix="incomplete",
        employee_id=employee_id,
        routine_run_id=routine_run_id,
        run_id=run_id,
        target=_target(ledger, "incomplete"),
        trajectory_refs=(
            _trajectory(ledger, "three"),
            _trajectory(ledger, "four"),
        ),
        evidence_ids=(_evidence(ledger, "two"),),
    )
    with pytest.raises(ValueError, match="routine run must be completed"):
        ledger.reflection_proposals.create(incomplete_routine)


def test_proposal_value_is_append_only_for_the_runtime_role(pg_database: str) -> None:
    import psycopg

    company_id = str(uuid.uuid4())
    ledger = Ledger.open(pg_database, company_id=company_id)
    try:
        employee_id, routine_run_id, run_id = _source(ledger, "append-only")
        proposal = ledger.reflection_proposals.create(
            _proposal(
                suffix="append-only",
                employee_id=employee_id,
                routine_run_id=routine_run_id,
                run_id=run_id,
                target=_target(ledger, "append-only"),
                trajectory_refs=(
                    _trajectory(ledger, "append-one"),
                    _trajectory(ledger, "append-two"),
                ),
                evidence_ids=(_evidence(ledger, "append-one"), _evidence(ledger, "append-two")),
            )
        )
    finally:
        ledger.close()

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
            "'chorus_reflection_app') THEN CREATE ROLE chorus_reflection_app LOGIN "
            "NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_reflection_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON reflection_proposal, "
            "reflection_proposal_evidence, reflection_proposal_trajectory TO chorus_reflection_app"
        )

    app_conninfo = pg_database.replace("user=postgres", "user=chorus_reflection_app")
    with psycopg.connect(app_conninfo, autocommit=True) as app:
        app.execute("SELECT set_config('app.company_id', %s, false)", (company_id,))
        updated = app.execute(
            "UPDATE reflection_proposal SET rationale = 'changed' "
            "WHERE artifact_revision_id = %s RETURNING artifact_revision_id",
            (proposal.artifact_revision_id,),
        ).fetchall()
        deleted = app.execute(
            "DELETE FROM reflection_proposal_evidence WHERE proposal_artifact_revision_id = %s "
            "RETURNING proposal_artifact_revision_id",
            (proposal.artifact_revision_id,),
        ).fetchall()
        changed_trajectory = app.execute(
            "UPDATE reflection_proposal_trajectory SET position = 9 "
            "WHERE proposal_artifact_revision_id = %s RETURNING proposal_artifact_revision_id",
            (proposal.artifact_revision_id,),
        ).fetchall()

    assert updated == []
    assert deleted == []
    assert changed_trajectory == []
