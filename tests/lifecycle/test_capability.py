"""CapabilityService — the manager's ledger-mutating capabilities (M3 Slice 1, spec 06 §4).

The dream-free seam a manager beat's `decompose` tool calls. It wraps the exact-once `decompose()`
lifecycle + assignment with the M3 idempotency rule: child ids are deterministic per `(parent, label)`,
so a tool re-fired within a beat (the generator retried) never creates duplicate children.
"""

from __future__ import annotations

import pytest

from chorus.ledger import Run, RunStatus, SqliteLedger, Task, TaskStatus
from chorus.lifecycle import DEFAULT_REQUEST_DEPTH_CAP
from chorus.lifecycle._capability import CapabilityService, ChildPlan
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

REV = "run_mgr_1"  # the manager's beat (run_id) — the decompose idempotency key


def _service(ledger: SqliteLedger, *, request_depth: int = 0) -> CapabilityService:
    ledger.employees.create(Employee(id="mgr", name="Mgr", role="manager"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.tasks.submit(
        Task(id="M", intent="ship the feature", status=TaskStatus.TODO,
             assignee_employee_id="mgr", request_depth=request_depth)
    )
    ledger.runs.create(Run(id=REV, employee_id="mgr", task_id="M", status=RunStatus.RUNNING))
    return CapabilityService(ledger)


def test_decompose_creates_assigned_children_gated_to_parent(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    res = svc.decompose(parent_id="M", revision=REV, children=[
        ChildPlan(label="api", intent="build the api", assignee="ada"),
        ChildPlan(label="ui", intent="build the ui", assignee="bob"),
    ])
    api, ui = res.child_ids["api"], res.child_ids["ui"]
    # children created under the parent, assigned to the named reports
    assert ledger.tasks.get(api).parent_id == "M"  # type: ignore[union-attr]
    assert ledger.tasks.get(api).assignee_employee_id == "ada"  # type: ignore[union-attr]
    assert ledger.tasks.get(ui).assignee_employee_id == "bob"  # type: ignore[union-attr]
    # the parent waits on every child via the M2 dependency gate (gates_parent)
    assert set(ledger.dependencies.unresolved_blockers("M")) == {api, ui}
    # each child is woken → dispatchable
    woken = {w.payload.get("task_id") for w in ledger.wakes.queued()}
    assert {api, ui} <= woken
    assert res.depth_capped is False


def test_idempotent_within_a_revision(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    plan = [ChildPlan(label="api", intent="build the api", assignee="ada")]
    r1 = svc.decompose(parent_id="M", revision=REV, children=plan)
    r2 = svc.decompose(parent_id="M", revision=REV, children=plan)  # the generator re-fired
    assert r1.child_ids == r2.child_ids  # same deterministic ids
    assert len(ledger.dependencies.unresolved_blockers("M")) == 1  # exactly one child, never duplicated


def test_inter_child_dependency_is_wired(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    res = svc.decompose(parent_id="M", revision=REV, children=[
        ChildPlan(label="api", intent="api", assignee="ada"),
        ChildPlan(label="tests", intent="tests", assignee="bob", depends_on=("api",)),
    ])
    # tests waits on api (a sibling edge), resolved by label
    assert ledger.dependencies.unresolved_blockers(res.child_ids["tests"]) == [res.child_ids["api"]]


def test_unknown_assignee_fails_closed_without_mutating(ledger: SqliteLedger) -> None:
    # A model may invent a report id; decompose must reject it cleanly *before* any mutation — never
    # leave an orphan child or a half-applied fan-out (proper tool envelope, validate at the boundary).
    svc = _service(ledger)
    res = svc.decompose(parent_id="M", revision=REV, children=[
        ChildPlan(label="api", intent="api", assignee="ada"),
        ChildPlan(label="ghost", intent="x", assignee="nobody"),  # not an employee
    ])
    assert res.unknown_assignees == ("nobody",)
    assert res.child_ids == {}
    assert ledger.dependencies.unresolved_blockers("M") == []  # nothing fanned out


def test_decompose_rejects_non_report_assignee_without_mutating(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    res = svc.decompose(
        parent_id="M",
        revision=REV,
        children=[ChildPlan(label="ops", intent="ops", assignee="eve")],
    )

    assert res.unknown_assignees == ("eve",)
    assert res.child_ids == {}
    assert ledger.dependencies.unresolved_blockers("M") == []


def test_decompose_allows_recursive_manager_report(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="lead", name="Lead", role="manager", reports_to="mgr"))

    res = svc.decompose(
        parent_id="M",
        revision=REV,
        children=[ChildPlan(label="platform", intent="delegate platform", assignee="lead")],
    )

    child = ledger.tasks.get(res.child_ids["platform"])
    assert child is not None
    assert child.assignee_employee_id == "lead"


def test_submit_one_adds_incremental_child_for_direct_report(ledger: SqliteLedger) -> None:
    svc = _service(ledger)

    res = svc.submit_one(
        parent_id="M",
        revision="run_mgr_integrate_1",
        child=ChildPlan(label="fix", intent="fix the gap", assignee="ada"),
    )

    assert res.child_id is not None
    child = ledger.tasks.get(res.child_id)
    assert child is not None
    assert child.parent_id == "M"
    assert child.assignee_employee_id == "ada"
    assert child.origin_fingerprint == "fix"
    assert ledger.dependencies.unresolved_blockers("M") == [res.child_id]


def test_submit_one_allows_recursive_manager_report(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="lead", name="Lead", role="manager", reports_to="mgr"))

    res = svc.submit_one(
        parent_id="M",
        revision="run_mgr_integrate_1",
        child=ChildPlan(label="platform", intent="delegate platform", assignee="lead"),
    )

    assert res.child_id is not None
    assert ledger.tasks.get(res.child_id).assignee_employee_id == "lead"  # type: ignore[union-attr]


def test_submit_one_rejects_non_report_without_mutating(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    res = svc.submit_one(
        parent_id="M",
        revision="run_mgr_integrate_1",
        child=ChildPlan(label="fix", intent="fix", assignee="eve"),
    )

    assert res.unknown_assignees == ("eve",)
    assert res.child_id is None
    assert ledger.dependencies.unresolved_blockers("M") == []


def test_reassign_routes_existing_child_to_direct_report(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    child_id = svc.submit_one(
        parent_id="M",
        revision="run_mgr_integrate_1",
        child=ChildPlan(label="fix", intent="fix", assignee="ada"),
    ).child_id
    assert child_id is not None

    result = svc.reassign(parent_id="M", task_id=child_id, assignee="bob", assigned_by="mgr")

    assert result.assigned is True
    assert ledger.tasks.get(child_id).assignee_employee_id == "bob"  # type: ignore[union-attr]
    assert any(w.employee_id == "bob" and w.payload.get("task_id") == child_id for w in ledger.wakes.queued())


def test_reassign_rejects_work_outside_parent_subtree(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    ledger.tasks.submit(Task(id="outside", intent="elsewhere", status=TaskStatus.TODO, assignee_employee_id="ada"))

    result = svc.reassign(parent_id="M", task_id="outside", assignee="bob", assigned_by="mgr")

    assert result.not_child is True
    assert result.assigned is False
    assert ledger.tasks.get("outside").assignee_employee_id == "ada"  # type: ignore[union-attr]


def test_reassign_rejects_non_report_assignee(ledger: SqliteLedger) -> None:
    svc = _service(ledger)
    child_id = svc.submit_one(
        parent_id="M",
        revision="run_mgr_integrate_1",
        child=ChildPlan(label="fix", intent="fix", assignee="ada"),
    ).child_id
    assert child_id is not None
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    result = svc.reassign(parent_id="M", task_id=child_id, assignee="eve", assigned_by="mgr")

    assert result.unknown_assignee == "eve"
    assert result.assigned is False
    assert ledger.tasks.get(child_id).assignee_employee_id == "ada"  # type: ignore[union-attr]


def test_depth_cap_fails_closed(ledger: SqliteLedger) -> None:
    svc = _service(ledger, request_depth=DEFAULT_REQUEST_DEPTH_CAP)  # one more level exceeds the cap
    res = svc.decompose(parent_id="M", revision=REV, children=[ChildPlan(label="x", intent="x", assignee="ada")])
    assert res.depth_capped is True
    assert res.child_ids == {}
    assert ledger.tasks.get("M").status is TaskStatus.BLOCKED  # type: ignore[union-attr]  # failed closed
