"""Manager/leaf observability projections over the durable ledger."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import Artifact, ArtifactType, DodStatus, Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.lifecycle import CapabilityService, ChildPlan
from chorus.observability import LedgerInspector
from chorus.outcomes import Verifier
from chorus.workforce import Employee


@pytest.fixture
def ledger() -> Iterator[SqliteLedger]:
    lg = SqliteLedger.open(":memory:")
    try:
        yield lg
    finally:
        lg.close()


def _seed_manager_tree(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(Task(id="M", intent="ship the feature", status=TaskStatus.TODO, assignee_employee_id="mgr"))
    ledger.runs.create(Run(id="run_mgr_1", employee_id="mgr", task_id="M", status=RunStatus.RUNNING))
    CapabilityService(ledger).decompose(
        parent_id="M",
        revision="run_mgr_1",
        children=(
            ChildPlan(label="api", intent="build api", assignee="ada"),
            ChildPlan(label="ui", intent="build ui", assignee="bob", depends_on=("api",)),
        ),
    )
    children = {task.origin_fingerprint: task for task in ledger.tasks.children("M")}
    api = children["api"]
    ledger.dod.create(api.id, Verifier.command("pytest -q"))
    ledger.runs.create(Run(id="run_api_1", employee_id="ada", task_id=api.id, status=RunStatus.SUCCEEDED, outcome={"summary": "api done"}))
    ledger.dod.record_verdict(ledger.dod.get_for_task(api.id).id, DodStatus.PASSED, run_id="run_api_1")  # type: ignore[union-attr]
    ledger.tasks.set_status(api.id, TaskStatus.DONE)
    ledger.artifacts.create(Artifact(id="art_api", task_id=api.id, type=ArtifactType.WORKSPACE_FILE, is_primary=True, resource_ref={"path": "api.py"}))
    ui = children["ui"]
    CapabilityService(ledger).reassign(parent_id="M", task_id=ui.id, assignee="ada", assigned_by="mgr")


def test_scrum_packet_view_counts_dependencies_completion_and_reassignments(ledger: SqliteLedger) -> None:
    _seed_manager_tree(ledger)

    view = LedgerInspector(ledger).scrum_packet("M")

    assert view.parent_task_id == "M"
    assert view.child_count == 2
    assert view.completed_children == 1
    assert view.completion_rate == 0.5
    assert view.dependency_edges == 3  # parent waits on both children, ui waits on api
    assert view.reassignments == 1
    api = next(child for child in view.children if child.label == "api")
    assert api.artifact_type == "workspace_file"


def test_org_observability_combines_leaf_and_manager_layers(ledger: SqliteLedger) -> None:
    _seed_manager_tree(ledger)

    report = LedgerInspector(ledger).org_report()

    assert report.employees == 3
    assert report.managers == 1
    assert report.leaves == 2
    assert report.tasks_total == 3
    assert report.tasks_done == 1
    assert report.completion_rate == 1 / 3
    assert report.decomposition_count == 1
    assert report.assignment_count == 3  # two initial child assignments + one reassign
    assert report.reassignment_count == 1
    assert report.manager_packets[0].parent_task_id == "M"


def test_integrate_packet_emission_is_audited(ledger: SqliteLedger, tmp_path) -> None:  # type: ignore[no-untyped-def]
    _seed_manager_tree(ledger)

    packet = IntegrateContextPacket.build(ledger, parent_task_id="M")
    packet.write(tmp_path)

    activity = ledger.activity.by_subject("task", "M")[-1]
    assert activity.verb.value == "scrum_packet"
    assert activity.payload["child_count"] == 2
    assert activity.payload["completed_children"] == 1