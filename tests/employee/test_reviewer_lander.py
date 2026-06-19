"""ReviewerLander — records a passed reviewer beat's verdict as a durable ``verdict`` artifact."""

from __future__ import annotations

import asyncio

import pytest

from chorus.ledger import SqliteLedger, Task, TaskStatus
from chorus.ledger._models import DodStatus
from chorus.outcomes import ArtifactType, Verifier
from chorus_employee import default_landers
from chorus_employee.reviewer import reviewer_lander

pytestmark = pytest.mark.integration


def test_reviewer_lander_records_the_verdict_artifact(ledger: SqliteLedger, tmp_path: object) -> None:
    ledger.tasks.submit(Task(id="spec", intent="write the spec", status=TaskStatus.IN_PROGRESS))
    dod = ledger.dod.create("spec", Verifier.agent_review(artifact_class="spec"))
    ledger.dod.record_verdict(
        dod.id, DodStatus.FAILED, verdict={"approve": False, "feedback": "needs section 3", "reviewer": "rob"}
    )
    task = ledger.tasks.get("spec")
    assert task is not None

    artifact = asyncio.run(reviewer_lander(ledger).land(task, None))

    assert artifact.type is ArtifactType.VERDICT and artifact.is_primary is True
    assert artifact.resource_ref == {
        "kind": "verdict", "approve": False, "feedback": "needs section 3", "reviewer": "rob"
    }


def test_default_landers_registers_the_verdict_lander(ledger: SqliteLedger, tmp_path: object) -> None:
    from pathlib import Path

    registry = default_landers(Path(str(tmp_path)), ledger=ledger)
    assert registry.get("verdict") is not None  # the kernel can land a reviewer beat
    assert registry.get("pr") is not None and registry.get("subtree") is not None
