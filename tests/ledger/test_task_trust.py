"""task.trust_preset + task.trust_boundary persistence (§4 trust presets)."""

from __future__ import annotations

import pytest

from chorus.ledger import Ledger, Task, TaskStatus
from chorus.testing import uid
from chorus.trust import TrustPreset

pytestmark = pytest.mark.integration


def test_trust_fields_default_to_none(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="ship", status=TaskStatus.TODO))
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.trust_preset is None and got.trust_boundary is None


def test_trust_preset_and_boundary_round_trip(ledger: Ledger) -> None:
    ledger.tasks.submit(
        Task(
            id=uid("t1"),
            intent="review an external PR",
            status=TaskStatus.TODO,
            trust_preset=TrustPreset.LOW_TRUST_REVIEW,
            trust_boundary={"secret_ref_allowlist": ["ref:github_token"]},
        )
    )
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    # stored as the StrEnum value (the model stays trust-module-free to avoid an import cycle).
    assert got.trust_preset == TrustPreset.LOW_TRUST_REVIEW
    assert got.trust_boundary == {"secret_ref_allowlist": ["ref:github_token"]}
