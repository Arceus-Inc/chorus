"""ActivityRepo — the append-only audit stream (spec 01 Cluster G ``activity``, spec 08 §5).

Every state transition a human might audit (assignment, decomposition, recovery, budget gate,
hire/fire, approval) lands here as an immutable row. Distinct from the spec 08 *event stream*
(operational telemetry) — ``activity`` is the durable, queryable subset that survives log rotation.
Actor is an employee XOR a human (null = the kernel itself).
"""

from __future__ import annotations

import pytest

from chorus.ledger import Activity, ActivityVerb, Ledger, LedgerIntegrityError
from chorus.testing import uid

pytestmark = pytest.mark.integration


def test_append_and_read_back(ledger: Ledger) -> None:
    rec = ledger.activity.append(
        Activity(
            id=uid("ac1"),
            verb=ActivityVerb.ASSIGNED,
            subject_kind="task",
            subject_id=uid("t1"),
            actor_employee_id="mgr",
            trace_id=uid("tr1"),
            payload={"to": "rep"},
        )
    )
    by_subject = ledger.activity.by_subject("task", uid("t1"))
    assert [a.id for a in by_subject] == [uid("ac1")]
    assert by_subject[0].verb is ActivityVerb.ASSIGNED
    assert by_subject[0].actor_employee_id == "mgr"
    assert by_subject[0].payload == {"to": "rep"}
    assert by_subject[0].occurred_at is not None
    assert rec.occurred_at is not None


def test_kernel_actor_allowed(ledger: Ledger) -> None:
    # null actor (both sides) = the kernel itself acted
    rec = ledger.activity.append(
        Activity(
            id=uid("ac1"), verb=ActivityVerb.RECOVERED, subject_kind="task", subject_id=uid("t1")
        )
    )
    assert rec.actor_employee_id is None
    assert rec.actor_user_id is None


def test_human_actor_allowed(ledger: Ledger) -> None:
    rec = ledger.activity.append(
        Activity(
            id=uid("ac1"),
            verb=ActivityVerb.APPROVED,
            subject_kind="approval",
            subject_id=uid("ap1"),
            actor_user_id=uid("u1"),
        )
    )
    assert rec.actor_user_id == uid("u1")
    assert rec.actor_employee_id is None


def test_single_actor_xor_enforced(ledger: Ledger) -> None:
    with pytest.raises(LedgerIntegrityError):
        ledger.activity.append(
            Activity(
                id=uid("ac1"),
                verb=ActivityVerb.GATED,
                subject_kind="task",
                subject_id=uid("t1"),
                actor_employee_id="mgr",
                actor_user_id=uid("u1"),  # both actors set → CHECK violation
            )
        )


def test_by_subject_is_scoped_and_ordered(ledger: Ledger) -> None:
    ledger.activity.append(
        Activity(
            id=uid("ac1"), verb=ActivityVerb.ASSIGNED, subject_kind="task", subject_id=uid("t1")
        )
    )
    ledger.activity.append(
        Activity(
            id=uid("ac2"), verb=ActivityVerb.DECOMPOSED, subject_kind="task", subject_id=uid("t1")
        )
    )
    ledger.activity.append(
        Activity(
            id=uid("ac3"), verb=ActivityVerb.HIRED, subject_kind="employee", subject_id=uid("e1")
        )
    )
    assert [a.id for a in ledger.activity.by_subject("task", uid("t1"))] == [uid("ac1"), uid("ac2")]


def test_recent_returns_newest_first(ledger: Ledger) -> None:
    for i in range(3):
        ledger.activity.append(
            Activity(
                id=uid(f"ac{i}"),
                verb=ActivityVerb.ASSIGNED,
                subject_kind="task",
                subject_id=uid(f"t{i}"),
            )
        )
    recent = ledger.activity.recent(limit=2)
    assert [a.id for a in recent] == [uid("ac2"), uid("ac1")]
