"""CapabilityService — the manager's ledger-mutating capabilities (M3 Slice 1, spec 06 §4).

The dream-free seam a manager beat's `decompose` tool calls. It wraps the exact-once `decompose()`
lifecycle + assignment with the M3 idempotency rule: child ids are deterministic per `(parent, label)`,
so a tool re-fired within a beat (the generator retried) never creates duplicate children.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    DelegationContract,
    DelegationContractStatus,
    ExecutionMode,
    Goal,
    Ledger,
    ManagementProfile,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.lifecycle import DEFAULT_REQUEST_DEPTH_CAP, MissionTeamPolicy
from chorus.lifecycle._capability import CapabilityService, ChildPlan
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

REV = uid("run_mgr_1")  # the manager's beat (run_id) — the decompose idempotency key


def _service(
    ledger: Ledger,
    *,
    request_depth: int = 0,
    parent_files_to_touch: tuple[str, ...] = (),
) -> CapabilityService:
    lead = ledger.employees.create(Employee(id="mgr", name="Mgr", role="engineer"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="mgr",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=DEFAULT_REQUEST_DEPTH_CAP,
            max_team_size=3,
            allowed_professions=("engineer",),
        )
    )
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    ledger.goals.create(Goal(id=uid("goal-M"), title="Ship the feature"))
    team_policy = MissionTeamPolicy(ledger)
    team = team_policy.create_for_root(lead, uid("goal-M"))
    team_policy.activate(team.id)
    ledger.tasks.submit(
        Task(
            id=uid("M"),
            intent="ship the feature",
            status=TaskStatus.TODO,
            execution_mode=ExecutionMode.DELEGATION,
            team_id=team.id,
            assignee_employee_id="mgr",
            goal_id=uid("goal-M"),
            request_depth=request_depth,
            files_to_touch=parent_files_to_touch,
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id=uid("M"),
            team_id=team.id,
            lead_employee_id="mgr",
            management_profile_version=1,
            can_subdelegate=True,
            max_depth=DEFAULT_REQUEST_DEPTH_CAP,
            max_team_size=3,
            objective_rubric="Ship the feature",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    ledger.runs.create(Run(id=REV, employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING))
    return CapabilityService(ledger)


def _start_integrating(ledger: Ledger) -> None:
    ledger.delegation_contracts.update_status(uid("M"), DelegationContractStatus.INTEGRATING)


def test_decompose_creates_assigned_children_gated_to_parent(ledger: Ledger) -> None:
    svc = _service(ledger)
    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(label="api", intent="build the api", assignee="ada"),
            ChildPlan(label="ui", intent="build the ui", assignee="bob"),
        ],
    )
    api, ui = res.child_ids["api"], res.child_ids["ui"]
    # children created under the parent, assigned to the named reports
    assert ledger.tasks.get(api).parent_id == uid("M")  # type: ignore[union-attr]
    assert ledger.tasks.get(api).assignee_employee_id == "ada"  # type: ignore[union-attr]
    assert ledger.tasks.get(ui).assignee_employee_id == "bob"  # type: ignore[union-attr]
    # the parent waits on every child via the M2 dependency gate (gates_parent)
    assert set(ledger.dependencies.unresolved_blockers(uid("M"))) == {api, ui}
    # each child is woken → dispatchable
    woken = {w.payload.get("task_id") for w in ledger.wakes.queued()}
    assert {api, ui} <= woken
    assert res.depth_capped is False


def test_decompose_rejects_a_deliverable_assigned_to_a_reviewer(ledger: Ledger) -> None:
    """A reviewer reviews (via the review beat); it can't *own* deliverable work (read-only + a
    human-approval DoD → it would strand). So decompose fails closed, naming the reviewer, and the
    manager reassigns the work to an engineer — nothing is created on the rejected path."""
    svc = _service(ledger)
    ledger.employees.create(Employee(id=uid("rev"), name="Rev", role="reviewer", reports_to="mgr"))
    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(label="impl", intent="build it", assignee="ada"),
            ChildPlan(
                label="qa", intent="run pytest + ruff", assignee=uid("rev")
            ),  # deliverable → a reviewer
        ],
    )
    assert res.reviewer_assignees == (uid("rev"),)
    assert res.child_ids == {}  # fail-closed: nothing created
    assert ledger.tasks.children(uid("M")) == []


def test_submit_one_rejects_a_deliverable_assigned_to_a_reviewer(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    ledger.employees.create(Employee(id=uid("rev"), name="Rev", role="reviewer", reports_to="mgr"))
    res = svc.submit_one(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        child=ChildPlan(label="qa", intent="checks", assignee=uid("rev")),
    )
    assert res.reviewer_assignees == (uid("rev"),)
    assert res.child_id is None


def test_idempotent_within_a_revision(ledger: Ledger) -> None:
    svc = _service(ledger)
    plan = [ChildPlan(label="api", intent="build the api", assignee="ada")]
    r1 = svc.decompose(parent_id=uid("M"), revision=REV, children=plan, actor_employee_id="mgr")
    r2 = svc.decompose(
        parent_id=uid("M"), revision=REV, children=plan, actor_employee_id="mgr"
    )  # the generator re-fired
    assert r1.child_ids == r2.child_ids  # same deterministic ids
    assert (
        len(ledger.dependencies.unresolved_blockers(uid("M"))) == 1
    )  # exactly one child, never duplicated


def test_inter_child_dependency_is_wired(ledger: Ledger) -> None:
    svc = _service(ledger)
    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(label="api", intent="api", assignee="ada"),
            ChildPlan(label="tests", intent="tests", assignee="bob", depends_on=("api",)),
        ],
    )
    # tests waits on api (a sibling edge), resolved by label
    assert ledger.dependencies.unresolved_blockers(res.child_ids["tests"]) == [res.child_ids["api"]]


def test_unknown_assignee_fails_closed_without_mutating(ledger: Ledger) -> None:
    # A model may invent a report id; decompose must reject it cleanly *before* any mutation — never
    # leave an orphan child or a half-applied fan-out (proper tool envelope, validate at the boundary).
    svc = _service(ledger)
    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(label="api", intent="api", assignee="ada"),
            ChildPlan(label=uid("ghost"), intent="x", assignee="nobody"),  # not an employee
        ],
    )
    assert res.unknown_assignees == ("nobody",)
    assert res.child_ids == {}
    assert ledger.dependencies.unresolved_blockers(uid("M")) == []  # nothing fanned out


def test_decompose_rejects_non_report_assignee_without_mutating(ledger: Ledger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[ChildPlan(label="ops", intent="ops", assignee="eve")],
    )

    assert res.unknown_assignees == ("eve",)
    assert res.child_ids == {}
    assert ledger.dependencies.unresolved_blockers(uid("M")) == []


def test_decompose_allows_specialist_lead_report(ledger: Ledger) -> None:
    svc = _service(ledger)
    ledger.employees.create(Employee(id="lead", name="Lead", role="engineer", reports_to="mgr"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="lead",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=1,
            max_team_size=2,
            allowed_professions=("engineer",),
        )
    )

    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[ChildPlan(label="platform", intent="delegate platform", assignee="lead")],
    )

    child = ledger.tasks.get(res.child_ids["platform"])
    assert child is not None
    assert child.assignee_employee_id == "lead"


def test_submit_one_adds_incremental_child_for_direct_report(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)

    res = svc.submit_one(
        parent_id=uid("M"),
        revision=uid("run_mgr_integrate_1"),
        actor_employee_id="mgr",
        child=ChildPlan(label="fix", intent="fix the gap", assignee="ada"),
    )

    assert res.child_id is not None
    child = ledger.tasks.get(res.child_id)
    assert child is not None
    assert child.parent_id == uid("M")
    assert child.assignee_employee_id == "ada"
    assert child.origin_fingerprint == "fix"
    assert ledger.dependencies.unresolved_blockers(uid("M")) == [res.child_id]


def test_submit_one_allows_specialist_lead_report(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    ledger.employees.create(Employee(id="lead", name="Lead", role="engineer", reports_to="mgr"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="lead",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=1,
            max_team_size=2,
            allowed_professions=("engineer",),
        )
    )

    res = svc.submit_one(
        parent_id=uid("M"),
        revision=uid("run_mgr_integrate_1"),
        actor_employee_id="mgr",
        child=ChildPlan(label="platform", intent="delegate platform", assignee="lead"),
    )

    assert res.child_id is not None
    assert ledger.tasks.get(res.child_id).assignee_employee_id == "lead"  # type: ignore[union-attr]


def test_submit_one_rejects_non_report_without_mutating(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    res = svc.submit_one(
        parent_id=uid("M"),
        revision=uid("run_mgr_integrate_1"),
        actor_employee_id="mgr",
        child=ChildPlan(label="fix", intent="fix", assignee="eve"),
    )

    assert res.unknown_assignees == ("eve",)
    assert res.child_id is None
    assert ledger.dependencies.unresolved_blockers(uid("M")) == []


def test_reassign_routes_existing_child_to_direct_report(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    child_id = svc.submit_one(
        parent_id=uid("M"),
        revision=uid("run_mgr_integrate_1"),
        actor_employee_id="mgr",
        child=ChildPlan(label="fix", intent="fix", assignee="ada"),
    ).child_id
    assert child_id is not None

    result = svc.reassign(parent_id=uid("M"), task_id=child_id, assignee="bob", assigned_by="mgr")

    assert result.assigned is True
    assert ledger.tasks.get(child_id).assignee_employee_id == "bob"  # type: ignore[union-attr]
    assert any(
        w.employee_id == "bob" and w.payload.get("task_id") == child_id
        for w in ledger.wakes.queued()
    )


def test_reassign_rejects_work_outside_parent_subtree(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    ledger.tasks.submit(
        Task(
            id=uid("outside"),
            intent="elsewhere",
            status=TaskStatus.TODO,
            assignee_employee_id="ada",
        )
    )

    result = svc.reassign(
        parent_id=uid("M"), task_id=uid("outside"), assignee="bob", assigned_by="mgr"
    )

    assert result.not_child is True
    assert result.assigned is False
    assert ledger.tasks.get(uid("outside")).assignee_employee_id == "ada"  # type: ignore[union-attr]


def test_reassign_rejects_non_report_assignee(ledger: Ledger) -> None:
    svc = _service(ledger)
    _start_integrating(ledger)
    child_id = svc.submit_one(
        parent_id=uid("M"),
        revision=uid("run_mgr_integrate_1"),
        actor_employee_id="mgr",
        child=ChildPlan(label="fix", intent="fix", assignee="ada"),
    ).child_id
    assert child_id is not None
    ledger.employees.create(Employee(id="eve", name="Eve", role="engineer"))

    result = svc.reassign(parent_id=uid("M"), task_id=child_id, assignee="eve", assigned_by="mgr")

    assert result.unknown_assignee == "eve"
    assert result.assigned is False
    assert ledger.tasks.get(child_id).assignee_employee_id == "ada"  # type: ignore[union-attr]


def test_depth_cap_fails_closed(ledger: Ledger) -> None:
    svc = _service(
        ledger, request_depth=DEFAULT_REQUEST_DEPTH_CAP
    )  # one more level exceeds the cap
    res = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[ChildPlan(label="x", intent="x", assignee="ada")],
    )
    assert res.depth_capped is True
    assert res.child_ids == {}
    assert ledger.tasks.get(uid("M")).status is TaskStatus.BLOCKED  # type: ignore[union-attr]  # failed closed


def test_legacy_unscoped_service_call_stays_unscoped(ledger: Ledger) -> None:
    svc = _service(ledger)

    result = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[ChildPlan(label="api", intent="build the api", assignee="ada")],
    )

    child = ledger.tasks.get(result.child_ids["api"])
    assert child is not None
    assert child.files_to_touch == ()


def test_scoped_parent_requires_scoped_children_even_for_direct_service_calls(ledger: Ledger) -> None:
    svc = _service(ledger, parent_files_to_touch=("src/api.py",))

    result = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[ChildPlan(label="api", intent="build the api", assignee="ada")],
    )

    assert result.scope_violations
    assert ledger.tasks.children(uid("M")) == []


def test_mixed_proposed_wave_rejects_pre_mutation_for_direct_service_calls(ledger: Ledger) -> None:
    svc = _service(ledger)

    result = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(
                label="api",
                intent="build the api",
                assignee="ada",
                files_to_touch=("src/api.py",),
            ),
            ChildPlan(label="ui", intent="build the ui", assignee="bob"),
        ],
    )

    assert result.scope_violations
    assert ledger.tasks.children(uid("M")) == []
    assert ledger.dependencies.unresolved_blockers(uid("M")) == []


def test_scope_changes_participate_in_exact_once_fingerprint(ledger: Ledger) -> None:
    svc = _service(ledger, parent_files_to_touch=("src/api.py", "src/other.py"))
    first = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(
                label="api",
                intent="build the api",
                assignee="ada",
                files_to_touch=("src/api.py",),
            ),
            ChildPlan(
                label="other",
                intent="build the other path",
                assignee="bob",
                files_to_touch=("src/other.py",),
            )
        ],
    )

    second = svc.decompose(
        parent_id=uid("M"),
        revision=REV,
        actor_employee_id="mgr",
        children=[
            ChildPlan(
                label="api",
                intent="build the api",
                assignee="ada",
                files_to_touch=("src/other.py",),
            ),
            ChildPlan(
                label="other",
                intent="build the other path",
                assignee="bob",
                files_to_touch=("src/api.py",),
            )
        ],
    )

    assert first.child_ids["api"]
    assert second.authority_denied == "this manager beat already committed a different child wave"
