"""Final human decisions for immutable Reflection Coach proposals."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

from chorus.ledger import (
    Ledger,
    LedgerIntegrityError,
    ReflectionProposalReview,
    ReflectionProposalVerdict,
)
from chorus.testing import uid

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _ProposalFixture:
    ledger: Ledger
    company_id: str
    proposal_revision_id: str


def _review(proposal_revision_id: str, suffix: str) -> ReflectionProposalReview:
    return ReflectionProposalReview(
        id=uid(f"proposal-review-{suffix}"),
        proposal_artifact_revision_id=proposal_revision_id,
        verdict=ReflectionProposalVerdict.ACCEPTED,
        reviewer_user_id=f"reviewer-{suffix}",
        reason="The visible diff is minimal and supported by the referenced trajectories.",
    )


def test_review_model_requires_a_human_reason_and_exact_proposal_revision() -> None:
    with pytest.raises(ValueError, match="proposal artifact revision id"):
        _review(" ", "blank-proposal")
    with pytest.raises(ValueError, match="reviewer user id"):
        ReflectionProposalReview(
            id=uid("blank-reviewer"),
            proposal_artifact_revision_id=uid("proposal-revision"),
            verdict=ReflectionProposalVerdict.REJECTED,
            reviewer_user_id=" ",
            reason="Needs narrower scope.",
        )
    with pytest.raises(ValueError, match="reason"):
        ReflectionProposalReview(
            id=uid("blank-reason"),
            proposal_artifact_revision_id=uid("proposal-revision"),
            verdict=ReflectionProposalVerdict.REJECTED,
            reviewer_user_id="founder",
            reason=" ",
        )


def test_final_review_round_trips_and_is_discoverable(
    ledger_with_reflection_proposal: _ProposalFixture,
) -> None:
    fixture = ledger_with_reflection_proposal
    proposal_revision_id = fixture.proposal_revision_id
    review = _review(proposal_revision_id, "accepted")

    recorded = fixture.ledger.reflection_proposal_reviews.record(review)

    assert recorded.created_at is not None
    assert recorded == fixture.ledger.reflection_proposal_reviews.get(review.id)
    assert (
        fixture.ledger.reflection_proposal_reviews.for_proposal(proposal_revision_id)
        == recorded
    )
    assert (
        fixture.ledger.reflection_proposal_reviews.accepted(proposal_revision_id)
        == recorded
    )


def test_rejected_review_never_appears_as_accepted(
    ledger_with_reflection_proposal: _ProposalFixture,
) -> None:
    fixture = ledger_with_reflection_proposal
    proposal_revision_id = fixture.proposal_revision_id
    review = ReflectionProposalReview(
        id=uid("proposal-review-rejected"),
        proposal_artifact_revision_id=proposal_revision_id,
        verdict=ReflectionProposalVerdict.REJECTED,
        reviewer_user_id="founder",
        reason="The proposed change is broader than the evidence supports.",
    )

    recorded = fixture.ledger.reflection_proposal_reviews.record(review)

    assert recorded.verdict is ReflectionProposalVerdict.REJECTED
    assert fixture.ledger.reflection_proposal_reviews.accepted(proposal_revision_id) is None


def test_proposal_has_exactly_one_final_human_decision(
    ledger_with_reflection_proposal: _ProposalFixture,
) -> None:
    fixture = ledger_with_reflection_proposal
    proposal_revision_id = fixture.proposal_revision_id
    fixture.ledger.reflection_proposal_reviews.record(
        _review(proposal_revision_id, "first")
    )

    with pytest.raises(LedgerIntegrityError):
        fixture.ledger.reflection_proposal_reviews.record(
            _review(proposal_revision_id, "second")
        )


def test_review_rejects_cross_tenant_proposal_revision(
    ledger_with_reflection_proposal: _ProposalFixture,
    pg_database: str,
) -> None:
    proposal_revision_id = ledger_with_reflection_proposal.proposal_revision_id
    other = Ledger.open(pg_database, company_id=str(uuid.uuid4()))
    try:
        with pytest.raises(LedgerIntegrityError):
            other.reflection_proposal_reviews.record(
                _review(proposal_revision_id, "cross-tenant")
            )
    finally:
        other.close()


def test_final_review_is_append_only_for_the_runtime_role(
    ledger_with_reflection_proposal: _ProposalFixture,
    pg_database: str,
) -> None:
    import psycopg

    fixture = ledger_with_reflection_proposal
    review = fixture.ledger.reflection_proposal_reviews.record(
        _review(fixture.proposal_revision_id, "append-only")
    )
    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = "
            "'chorus_review_app') THEN CREATE ROLE chorus_review_app LOGIN "
            "NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO chorus_review_app")
        admin.execute(
            "GRANT SELECT, INSERT, UPDATE, DELETE ON reflection_proposal_review "
            "TO chorus_review_app"
        )

    app_conninfo = pg_database.replace("user=postgres", "user=chorus_review_app")
    with psycopg.connect(app_conninfo, autocommit=True) as app:
        app.execute("SELECT set_config('app.company_id', %s, false)", (fixture.company_id,))
        updated = app.execute(
            "UPDATE reflection_proposal_review SET verdict = 'rejected' "
            "WHERE id = %s RETURNING id",
            (review.id,),
        ).fetchall()
        deleted = app.execute(
            "DELETE FROM reflection_proposal_review WHERE id = %s RETURNING id",
            (review.id,),
        ).fetchall()

    assert updated == []
    assert deleted == []


@pytest.fixture
def ledger_with_reflection_proposal(pg_database: str) -> Iterator[_ProposalFixture]:
    """Reuse the proposal suite's builders to create one valid immutable proposal."""
    from tests.ledger.test_reflection_proposals import (
        _evidence,
        _proposal,
        _source,
        _target,
        _trajectory,
    )

    company_id = str(uuid.uuid4())
    ledger = Ledger.open(pg_database, company_id=company_id)
    try:
        employee_id, routine_run_id, run_id = _source(ledger, "review")
        proposal = ledger.reflection_proposals.create(
            _proposal(
                suffix="review",
                employee_id=employee_id,
                routine_run_id=routine_run_id,
                run_id=run_id,
                target=_target(ledger, "review"),
                trajectory_refs=(
                    _trajectory(ledger, "review-one"),
                    _trajectory(ledger, "review-two"),
                ),
                evidence_ids=(_evidence(ledger, "review"),),
            )
        )
        yield _ProposalFixture(ledger, company_id, proposal.artifact_revision_id)
    finally:
        ledger.close()
