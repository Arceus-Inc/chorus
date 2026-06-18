"""BeatContext + IntegrateContextPacket — the manager's per-beat operating packet."""

from __future__ import annotations

from pathlib import Path

import pytest

from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import Artifact, ArtifactType, DodStatus, Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def test_integrate_context_packet_summarizes_child_feedback(
    ledger: SqliteLedger, tmp_path: Path
) -> None:
    ledger.employees.create(Employee(id="mgr", name="Mgr", role="manager"))
    ledger.employees.create(Employee(id="lead", name="Lead", role="manager", reports_to="mgr"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="lead"))
    ledger.tasks.submit(Task(id="P", intent="ship the pantry", status=TaskStatus.BLOCKED, assignee_employee_id="mgr"))
    ledger.tasks.submit(
        Task(
            id="C1",
            parent_id="P",
            intent="build storage",
            status=TaskStatus.DONE,
            assignee_employee_id="lead",
        )
    )
    ledger.runs.create(
        Run(
            id="run_c1",
            employee_id="lead",
            task_id="C1",
            status=RunStatus.SUCCEEDED,
            outcome={"summary": "storage landed", "cost_cents": 4},
        )
    )
    dod = ledger.dod.create("C1", Verifier.command("python -m pytest", artifact_class="file"))
    ledger.dod.record_verdict(dod.id, DodStatus.PASSED, verdict={"stdout": "ok"}, run_id="run_c1")
    ledger.artifacts.create(
        Artifact(
            id="art_c1",
            task_id="C1",
            type=ArtifactType.PR,
            is_primary=True,
            resource_ref={"merged": True, "commit": "abc123"},
        )
    )

    packet = IntegrateContextPacket.build(ledger, parent_task_id="P", iteration=2)
    packet.write(tmp_path)
    loaded = IntegrateContextPacket.read(tmp_path)

    assert loaded.parent_task_id == "P"
    assert loaded.parent_intent == "ship the pantry"
    assert loaded.iteration == 2
    assert [(report.id, report.role) for report in loaded.available_reports] == [("lead", "manager")]
    child = loaded.children[0]
    assert child.task_id == "C1"
    assert child.assignee == "lead"
    assert child.assignee_role == "manager"
    assert child.status == "done"
    assert child.dod_status == "passed"
    assert child.latest_run_status == "succeeded"
    assert child.latest_run_summary == "storage landed"
    assert child.artifact_type == "pr"
    assert child.artifact_ref == {"merged": True, "commit": "abc123"}
