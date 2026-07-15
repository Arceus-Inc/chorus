"""Manager/leaf observability projections over the durable ledger."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from chorus.heartbeat import IntegrateContextPacket
from chorus.ledger import (
    Artifact,
    ArtifactType,
    DelegationContract,
    DelegationContractStatus,
    DodStatus,
    ExecutionMode,
    Goal,
    ManagementProfile,
    Run,
    RunStatus,
    SqliteLedger,
    Task,
    TaskStatus,
    Team,
    TeamMember,
    TeamMembershipRole,
    TeamStatus,
)
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
    ledger.employees.create(Employee(id="mgr", name="Moe", role="backend_engineer"))
    ledger.employees.create(
        Employee(id="ada", name="Ada", role="backend_engineer", reports_to="mgr")
    )
    ledger.employees.create(
        Employee(id="bob", name="Bob", role="backend_engineer", reports_to="mgr")
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="mgr",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            max_delegation_depth=1,
            max_team_size=3,
            allowed_professions=("backend_engineer",),
            version=1,
        )
    )
    ledger.goals.create(Goal(id="goal-M", title="Ship the feature"))
    ledger.teams.create(
        Team(
            id="team-M",
            name="Feature Team",
            lead_employee_id="mgr",
            created_by="operator",
            status=TeamStatus.ACTIVE,
        )
    )
    ledger.team_members.add(
        TeamMember(
            team_id="team-M",
            employee_id="mgr",
            source_manager_id="mgr",
            membership_role=TeamMembershipRole.LEAD,
        )
    )
    ledger.tasks.submit(
        Task(
            id="M",
            intent="ship the feature",
            status=TaskStatus.TODO,
            assignee_employee_id="mgr",
            execution_mode=ExecutionMode.DELEGATION,
            team_id="team-M",
            goal_id="goal-M",
        )
    )
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id="M",
            team_id="team-M",
            lead_employee_id="mgr",
            management_profile_version=1,
            max_depth=1,
            max_team_size=3,
            objective_rubric="the complete feature is integrated",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    ledger.runs.create(
        Run(id="run_mgr_1", employee_id="mgr", task_id="M", status=RunStatus.RUNNING)
    )
    CapabilityService(ledger).decompose(
        parent_id="M",
        revision="run_mgr_1",
        children=(
            ChildPlan(label="api", intent="build api", assignee="ada"),
            ChildPlan(label="ui", intent="build ui", assignee="bob", depends_on=("api",)),
        ),
        actor_employee_id="mgr",
    )
    ledger.delegation_contracts.update_status("M", DelegationContractStatus.INTEGRATING)
    children = {task.origin_fingerprint: task for task in ledger.tasks.children("M")}
    api = children["api"]
    ledger.dod.create(api.id, Verifier.command("pytest -q"))
    ledger.runs.create(
        Run(
            id="run_api_1",
            employee_id="ada",
            task_id=api.id,
            status=RunStatus.SUCCEEDED,
            outcome={"summary": "api done"},
        )
    )
    ledger.dod.record_verdict(
        ledger.dod.get_for_task(api.id).id, DodStatus.PASSED, run_id="run_api_1"
    )  # type: ignore[union-attr]
    ledger.tasks.set_status(api.id, TaskStatus.DONE)
    ledger.artifacts.create(
        Artifact(
            id="art_api",
            task_id=api.id,
            type=ArtifactType.WORKSPACE_FILE,
            is_primary=True,
            resource_ref={"path": "api.py"},
        )
    )
    ui = children["ui"]
    CapabilityService(ledger).reassign(
        parent_id="M", task_id=ui.id, assignee="ada", assigned_by="mgr"
    )


def test_scrum_packet_view_counts_dependencies_completion_and_reassignments(
    ledger: SqliteLedger,
) -> None:
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


def test_inspector_exposes_management_authority_and_delegation_views(
    ledger: SqliteLedger,
) -> None:
    ledger.employees.create(Employee(id="lead", name="Lead", role="engineer"))
    ledger.employees.create(
        Employee(id="member", name="Member", role="designer", reports_to="lead")
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="lead",
            granted_by_user_id="user-admin",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=2,
            max_team_size=4,
            allowed_professions=("engineer", "designer"),
            spend_limit_cents=50_000,
        )
    )
    ledger.teams.create(
        Team(
            id="team-alpha",
            name="Alpha",
            lead_employee_id="lead",
            created_by="user-admin",
            status=TeamStatus.ACTIVE,
            policy_version=3,
        )
    )
    for employee_id, membership_role in (
        ("lead", TeamMembershipRole.LEAD),
        ("member", TeamMembershipRole.MEMBER),
    ):
        ledger.team_members.add(
            TeamMember(
                team_id="team-alpha",
                employee_id=employee_id,
                source_manager_id="lead",
                membership_role=membership_role,
                can_subdelegate=employee_id == "lead",
            )
        )
    ledger.tasks.submit(Task(id="task-alpha", intent="Ship Alpha"))
    ledger.delegation_contracts.create(
        DelegationContract(
            task_id="task-alpha",
            team_id="team-alpha",
            lead_employee_id="lead",
            management_profile_version=1,
            objective_rubric="all Alpha outcomes are integrated and verified",
            can_subdelegate=True,
            max_depth=2,
            max_team_size=4,
            max_direct_children=2,
            spend_limit_cents=50_000,
            status=DelegationContractStatus.DELEGATED,
        )
    )

    inspector = LedgerInspector(ledger)
    team = inspector.teams()[0]
    contract = inspector.delegation_contracts()[0]
    profile = inspector.management_profiles()[0]

    assert (team.id, team.status, team.lead_employee_id, team.member_employee_ids) == (
        "team-alpha",
        TeamStatus.ACTIVE,
        "lead",
        ("lead", "member"),
    )
    assert (team.goal_id, team.policy_version) == (None, 3)
    assert (
        contract.task_id,
        contract.team_id,
        contract.status,
        contract.management_profile_version,
    ) == ("task-alpha", "team-alpha", DelegationContractStatus.DELEGATED, 1)
    assert (contract.max_depth, contract.max_team_size, contract.spend_limit_cents) == (
        2,
        4,
        50_000,
    )
    assert contract.max_direct_children == 2
    assert (profile.employee_id, profile.active, profile.version) == ("lead", True, 1)
    assert (profile.max_delegation_depth, profile.max_team_size) == (2, 4)
    assert profile.allowed_professions == ("engineer", "designer")
