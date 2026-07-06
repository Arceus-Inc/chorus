"""The ``org.trust`` group + ``submit(trust=…)`` (spec 14 §5.3) — a task's trust posture."""

from __future__ import annotations

import pytest

from chorus.facade import Caps, Chorus
from chorus.ledger import SqliteLedger, Task
from chorus.observability import EventBus, LedgerInspector
from chorus.roles import RoleRegistry, default_roles
from chorus.trust import TrustPreset
from chorus.workforce import LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: SqliteLedger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=EventBus(),
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def test_set_task_trust_round_trips() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        ledger.tasks.submit(Task(id="t1", intent="review an external PR"))
        _chorus(ledger).trust.set_task(
            "t1",
            preset=TrustPreset.LOW_TRUST_REVIEW,
            boundary={"secret_ref_allowlist": ["ref:github_token"]},
        )
        stored = ledger.tasks.get("t1")
        assert stored is not None
        assert stored.trust_preset == TrustPreset.LOW_TRUST_REVIEW
        assert stored.trust_boundary == {"secret_ref_allowlist": ["ref:github_token"]}
    finally:
        ledger.close()


def test_submit_sets_trust_at_creation() -> None:
    ledger = SqliteLedger.open(":memory:")
    try:
        task = _chorus(ledger).submit(
            "review an external PR",
            trust_preset=TrustPreset.LOW_TRUST_REVIEW,
            trust_boundary={"secret_ref_allowlist": ["ref:token"]},
        )
        stored = ledger.tasks.get(task.id)
        assert stored is not None
        assert stored.trust_preset == TrustPreset.LOW_TRUST_REVIEW
    finally:
        ledger.close()
