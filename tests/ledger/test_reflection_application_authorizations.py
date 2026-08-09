"""Accepted reflection proposals authorize application only in a separate queued run."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace

import pytest

from chorus.ledger import (
    Ledger,
    LedgerIntegrityError,
    ReflectionApplicationAuthorization,
    ReflectionProposalReview,
    ReflectionProposalVerdict,
    Run,
    RunStatus,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _ReviewedProposal:
    proposal_revision_id: str
    proposal_source_run_id: str
    review_id: str
    reviewer_user_id: str


def _reviewed_proposal(
    ledger: Ledger,
    suffix: str,
    *,
    verdict: ReflectionProposalVerdict = ReflectionProposalVerdict.ACCEPTED,
) -> _ReviewedProposal:
    from tests.ledger.test_reflection_proposals import (
        _evidence,
        _proposal,
        _source,
        _target,
        _trajectory,
    )

    employee_id, routine_run_id, source_run_id = _source(
        ledger,
        suffix,
        employee_id=f"reflection-coach-{suffix}",
    )
    proposal = ledger.reflection_proposals.create(
        _proposal(
            suffix=suffix,
            employee_id=employee_id,
            routine_run_id=routine_run_id,
            run_id=source_run_id,
            target=_target(ledger, suffix),
            trajectory_refs=(
                _trajectory(ledger, f"{suffix}-one"),
                _trajectory(ledger, f"{suffix}-two"),
            ),
            evidence_ids=(_evidence(ledger, suffix),),
        )
    )
    reviewer_user_id = f"reviewer-{suffix}"
    review = ledger.reflection_proposal_reviews.record(
        ReflectionProposalReview(
            id=uid(f"application-review-{suffix}"),
            proposal_artifact_revision_id=proposal.artifact_revision_id,
            verdict=verdict,
            reviewer_user_id=reviewer_user_id,
            reason="The visible diff and replay evidence support a separate application run.",
        )
    )
    return _ReviewedProposal(
        proposal_revision_id=proposal.artifact_revision_id,
        proposal_source_run_id=source_run_id,
        review_id=review.id,
        reviewer_user_id=reviewer_user_id,
    )


def _application_run(ledger: Ledger, suffix: str, *, status: RunStatus = RunStatus.QUEUED) -> Run:
    employee_id = f"application-agent-{suffix}"
    ledger.employees.create(Employee(id=employee_id, name="Application Agent", role="engineer"))
    task = ledger.tasks.submit(
        Task(id=uid(f"application-task-{suffix}"), intent="apply accepted reflection proposal")
    )
    return ledger.runs.create(
        Run(
            id=uid(f"application-run-{suffix}"),
            employee_id=employee_id,
            task_id=task.id,
            status=status,
        )
    )


def _authorization(
    accepted: _ReviewedProposal,
    application_run_id: str,
    suffix: str,
) -> ReflectionApplicationAuthorization:
    return ReflectionApplicationAuthorization(
        id=uid(f"application-authorization-{suffix}"),
        proposal_artifact_revision_id=accepted.proposal_revision_id,
        review_id=accepted.review_id,
        proposal_source_run_id=accepted.proposal_source_run_id,
        application_run_id=application_run_id,
        authorized_by_user_id=accepted.reviewer_user_id,
    )


def test_authorization_model_rejects_same_run_or_blank_identity() -> None:
    source_run_id = uid("same-run")
    with pytest.raises(ValueError, match="separate run"):
        ReflectionApplicationAuthorization(
            id=uid("same-run-authorization"),
            proposal_artifact_revision_id=uid("proposal"),
            review_id=uid("review"),
            proposal_source_run_id=source_run_id,
            application_run_id=source_run_id,
            authorized_by_user_id="founder",
        )
    with pytest.raises(ValueError, match="authorized by user id"):
        ReflectionApplicationAuthorization(
            id=uid("blank-reviewer-authorization"),
            proposal_artifact_revision_id=uid("proposal"),
            review_id=uid("review"),
            proposal_source_run_id=uid("source-run"),
            application_run_id=uid("application-run"),
            authorized_by_user_id=" ",
        )


def test_accepted_review_authorizes_one_separate_queued_run(ledger: Ledger) -> None:
    accepted = _reviewed_proposal(ledger, "accepted")
    application_run = _application_run(ledger, "accepted")
    authorization = _authorization(accepted, application_run.id, "accepted")

    recorded = ledger.reflection_application_authorizations.issue(authorization)

    assert recorded.created_at is not None
    assert recorded == ledger.reflection_application_authorizations.get(recorded.id)
    assert (
        ledger.reflection_application_authorizations.for_proposal(accepted.proposal_revision_id)
        == recorded
    )
    assert (
        ledger.reflection_application_authorizations.for_run(application_run.id) == recorded
    )


def test_rejected_or_mismatched_review_cannot_authorize_application(ledger: Ledger) -> None:
    accepted = _reviewed_proposal(ledger, "mismatch")
    application_run = _application_run(ledger, "mismatch")
    authorization = _authorization(accepted, application_run.id, "mismatch")

    with pytest.raises(ValueError, match="accepted human review"):
        ledger.reflection_application_authorizations.issue(
            replace(authorization, authorized_by_user_id="another-reviewer")
        )

    rejected_proposal = _reviewed_proposal(
        ledger,
        "rejected",
        verdict=ReflectionProposalVerdict.REJECTED,
    )
    with pytest.raises(ValueError, match="accepted human review"):
        ledger.reflection_application_authorizations.issue(
            _authorization(
                rejected_proposal,
                _application_run(ledger, "rejected").id,
                "rejected",
            )
        )


def test_finished_run_cannot_receive_retroactive_application_authority(ledger: Ledger) -> None:
    accepted = _reviewed_proposal(ledger, "finished")
    finished_run = _application_run(ledger, "finished", status=RunStatus.SUCCEEDED)

    with pytest.raises(ValueError, match="queued"):
        ledger.reflection_application_authorizations.issue(
            _authorization(accepted, finished_run.id, "finished")
        )


def test_proposal_and_application_run_are_each_single_use(ledger: Ledger) -> None:
    accepted = _reviewed_proposal(ledger, "single-use")
    first_run = _application_run(ledger, "single-use-first")
    ledger.reflection_application_authorizations.issue(
        _authorization(accepted, first_run.id, "single-use-first")
    )

    with pytest.raises(LedgerIntegrityError):
        ledger.reflection_application_authorizations.issue(
            _authorization(
                accepted,
                _application_run(ledger, "single-use-second").id,
                "single-use-second",
            )
        )

    another = _reviewed_proposal(ledger, "another")
    with pytest.raises(LedgerIntegrityError):
        ledger.reflection_application_authorizations.issue(
            _authorization(another, first_run.id, "reuse-run")
        )


def test_cross_tenant_application_run_fails_closed(pg_database: str) -> None:
    company_a = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    company_b = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        accepted = _reviewed_proposal(company_a, "cross-tenant")
        foreign_run = _application_run(company_b, "cross-tenant")

        with pytest.raises(LedgerIntegrityError):
            company_a.reflection_application_authorizations.issue(
                _authorization(accepted, foreign_run.id, "cross-tenant")
            )
    finally:
        company_b.close()
        company_a.close()
