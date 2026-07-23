"""CapabilityService.record_decision — the atomic, idempotent Decision OS write (§10, slice 2).

The service is a pure kernel writer: it records the DecisionRecord and its Claim rows in one
transaction and is idempotent per ``(task_id, revision)``. It holds NO confidence policy — the floor
is PM domain knowledge enforced one layer up in the tool (checklist J2: the kernel does not import an
employee package).
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger
from chorus.ledger._models import RejectedAlternative
from chorus.lifecycle._capability import CapabilityService, ClaimDraft, DecisionOutcome
from chorus.testing import uid

pytestmark = pytest.mark.integration

_CLAIMS = [
    ClaimDraft(text="temporal surfaces execution state", source_url="https://a", confidence=0.9),
    ClaimDraft(text="stuck runs still look green", source_url="https://b", confidence=0.7),
]
_REJECTED = [RejectedAlternative(option="second provider", reason="outages are rare")]


def _record(service: CapabilityService, *, revision: str = "r1") -> DecisionOutcome:
    return service.record_decision(
        task_id=uid("t1"),
        revision=revision,
        option="build presence indicators",
        rationale="run opacity is the top complaint",
        confidence=0.82,
        outcome_metric="'stuck' tickets drop 30%",
        revisit_trigger="if flat in 4 weeks, reopen",
        rejected=_REJECTED,
        claims=_CLAIMS,
    )


def test_records_the_decision_and_its_claims(ledger: Ledger) -> None:
    outcome = _record(CapabilityService(ledger))
    assert outcome.recorded is True and outcome.idempotent is False

    decisions = ledger.decisions.for_task(uid("t1"))
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.option == "build presence indicators"
    assert decision.rejected_alternatives[0].reason == "outages are rare"

    claims = ledger.claims.for_decisions([decision.id])
    assert {c.source_url for c in claims} == {"https://a", "https://b"}
    assert all(c.decision_id == decision.id for c in claims)


def test_is_idempotent_per_task_revision(ledger: Ledger) -> None:
    service = CapabilityService(ledger)
    first = _record(service)
    second = _record(service)  # same (task, revision)
    assert second.decision_id == first.decision_id
    assert second.recorded is False and second.idempotent is True
    assert len(ledger.decisions.for_task(uid("t1"))) == 1
    assert len(ledger.claims.for_decisions([first.decision_id])) == 2  # not doubled


def test_fresh_record_returns_the_canonical_content(ledger: Ledger) -> None:
    outcome = _record(CapabilityService(ledger))
    assert outcome.record is not None
    assert outcome.record.option == "build presence indicators"
    assert {c.source_url for c in outcome.claims} == {"https://a", "https://b"}


def test_idempotent_refire_returns_the_already_recorded_decision(ledger: Ledger) -> None:
    """A second call in the same beat is a no-op on the ledger AND reports the recorded decision.

    The immutable record wins: a re-fire with *different* content must not report the rejected new
    input, or the caller (the tool that mirrors decision.json) drifts from the ledger.
    """
    service = CapabilityService(ledger)
    first = _record(service, revision="r1")  # option "build presence indicators"
    second = service.record_decision(
        task_id=uid("t1"),
        revision="r1",  # same beat -> idempotent
        option="build a run timeline instead",  # DIFFERENT content
        rationale="changed my mind",
        confidence=0.9,
        outcome_metric="m",
        revisit_trigger="t",
        rejected=[],
        claims=[ClaimDraft(text="z", source_url="https://z", confidence=0.9)],
    )
    assert second.idempotent is True and second.recorded is False
    assert second.decision_id == first.decision_id
    assert second.record is not None
    assert second.record.option == "build presence indicators"  # the FIRST, authoritative one
    assert {c.source_url for c in second.claims} == {"https://a", "https://b"}  # first's claims


def test_a_new_revision_supersedes_with_a_distinct_id(ledger: Ledger) -> None:
    service = CapabilityService(ledger)
    first = _record(service, revision="r1")
    second = _record(service, revision="r2")
    assert second.decision_id != first.decision_id
    assert {d.id for d in ledger.decisions.for_task(uid("t1"))} == {
        first.decision_id,
        second.decision_id,
    }


def test_write_is_atomic_a_bad_claim_rolls_back_the_decision(ledger: Ledger) -> None:
    service = CapabilityService(ledger)
    bad_claims = [ClaimDraft(text="ok", source_url="https://a", confidence=0.9), None]  # type: ignore[list-item]
    with pytest.raises((AttributeError, TypeError)):
        service.record_decision(
            task_id=uid("t1"),
            revision="r1",
            option="x",
            rationale="y",
            confidence=0.82,
            outcome_metric="m",
            revisit_trigger="t",
            rejected=[],
            claims=bad_claims,
        )
    assert (
        ledger.decisions.for_task(uid("t1")) == []
    )  # the decision row rolled back with the claim failure
