"""DecisionRepo + ClaimRepo — the Decision OS storage rows (pm design doc §10).

A PM decision is an immutable, cited ledger object: a :class:`DecisionRecord` (the bet, its
confidence, the rejected alternatives, and a revisit trigger) plus the :class:`Claim` rows that
ground it. A change never mutates a record — it supersedes with a new id. These tests pin the
round-trip, the supersede-not-mutate invariant, and the batched claim read (no N+1 when a packet
spans many decisions).
"""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger
from chorus.ledger._models import Claim, DecisionRecord, RejectedAlternative
from chorus.testing import uid

pytestmark = pytest.mark.integration


def _decision(
    decision_id: str = uid("d1"),
    task_id: str = uid("t1"),
    *,
    confidence: float = 0.82,
    superseded_by: str | None = None,
) -> DecisionRecord:
    return DecisionRecord(
        id=decision_id,
        task_id=task_id,
        option="build live presence indicators",
        rationale="run opacity is the single largest support tag this month",
        confidence=confidence,
        outcome_metric="support tickets tagged 'stuck' drop 30% in 4 weeks",
        revisit_trigger="if the tag doesn't fall within 4 weeks, reopen",
        rejected_alternatives=(
            RejectedAlternative(option="second LLM provider", reason="provider outages are rare"),
        ),
        superseded_by=superseded_by,
    )


class TestDecisionRepo:
    def test_create_and_get_round_trip(self, ledger: Ledger) -> None:
        ledger.decisions.create(_decision())
        got = ledger.decisions.get(uid("d1"))
        assert got is not None
        assert got.option == "build live presence indicators"
        assert got.confidence == 0.82
        assert got.revisit_trigger.startswith("if the tag")
        assert got.rejected_alternatives[0].reason == "provider outages are rare"
        assert got.superseded_by is None
        assert got.created_at is not None

    def test_get_missing_returns_none(self, ledger: Ledger) -> None:
        assert ledger.decisions.get(uid("nope")) is None

    def test_for_task_returns_all_for_the_task(self, ledger: Ledger) -> None:
        ledger.decisions.create(_decision(decision_id=uid("d1")))
        ledger.decisions.create(_decision(decision_id=uid("d2")))
        ledger.decisions.create(_decision(decision_id=uid("d3"), task_id=uid("other")))
        assert {d.id for d in ledger.decisions.for_task(uid("t1"))} == {uid("d1"), uid("d2")}

    def test_supersede_is_a_pointer_not_a_mutation(self, ledger: Ledger) -> None:
        ledger.decisions.create(_decision(decision_id=uid("d1")))
        ledger.decisions.create(_decision(decision_id=uid("d2")))  # the successor
        ledger.decisions.set_superseded_by(uid("d1"), uid("d2"))
        assert ledger.decisions.get(uid("d1")).superseded_by == uid("d2")
        assert ledger.decisions.get(uid("d2")).superseded_by is None  # d2 stays live


class TestClaimRepo:
    def test_create_and_batch_fetch_for_decisions(self, ledger: Ledger) -> None:
        ledger.decisions.create(_decision(decision_id=uid("d1")))
        ledger.decisions.create(_decision(decision_id=uid("d2")))
        ledger.claims.create(
            Claim(
                id=uid("c1"),
                decision_id=uid("d1"),
                text="temporal shows state",
                source_url="https://a",
                confidence=0.9,
            )
        )
        ledger.claims.create(
            Claim(
                id=uid("c2"),
                decision_id=uid("d1"),
                text="stuck runs look green",
                source_url="https://b",
                confidence=0.7,
            )
        )
        ledger.claims.create(
            Claim(
                id=uid("c3"),
                decision_id=uid("d2"),
                text="unrelated",
                source_url="https://c",
                confidence=0.5,
            )
        )
        batched = ledger.claims.for_decisions([uid("d1"), uid("d2")])
        assert {c.id for c in batched} == {uid("c1"), uid("c2"), uid("c3")}
        assert {c.id for c in ledger.claims.for_decisions([uid("d1")])} == {uid("c1"), uid("c2")}

    def test_for_decisions_empty_input_returns_empty(self, ledger: Ledger) -> None:
        assert ledger.claims.for_decisions([]) == []
