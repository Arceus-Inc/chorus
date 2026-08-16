"""Capability-matched routing — a manager's DELIVERY child is re-routed to the right craft.

Live symptom (run7-9): a lead cross-assigned craft work to whoever was on the pod — an ``analyst``
handed a code/CI subtask — so the deliverable was produced by the wrong craft and rejected, burning a
beat before the manager re-assigned. F1 already judges a cross-assignment by the *deliverable's* own
standard (so correct work isn't rejected for the wrong rubric); this closes the other half — don't
*route* a strongly-mismatched deliverable to the wrong craft in the first place when a better-matched
report is free. The routing is deterministic and derived from the role registry (each role's native
deliverable kind is read from its own DoD), never a hardcoded task→role table, and it fires ONLY on an
unambiguous cross-craft mismatch with a strictly-better free report — canonical/ambiguous work and
pods that lack the ideal craft are left exactly as the manager asked.
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
from chorus.lifecycle._capability import (
    CapabilityService,
    ChildPlan,
    DecomposeResult,
    SubmitTaskResult,
)
from chorus.outcomes import OutcomeKind
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

REV = uid("run_mgr_1")


def _service(
    ledger: Ledger, *, reports: tuple[tuple[str, str], ...], with_roles: bool = True
) -> CapabilityService:
    """A delegation manager whose team is ``reports`` (id, profession); routing-enabled by default."""
    lead = ledger.employees.create(Employee(id="mgr", name="Mgr", role="pm"))
    professions = tuple({role for _, role in reports} | {"pm"})
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="mgr",
            granted_by_user_id="operator",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=DEFAULT_REQUEST_DEPTH_CAP,
            max_team_size=6,
            allowed_professions=professions,
        )
    )
    for emp_id, role in reports:
        ledger.employees.create(
            Employee(id=emp_id, name=emp_id.title(), role=role, reports_to="mgr")
        )
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
            max_team_size=6,
            objective_rubric="Ship the feature",
            status=DelegationContractStatus.DELEGATED,
        )
    )
    ledger.runs.create(Run(id=REV, employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING))
    roles = RoleRegistry.from_plugins(default_roles()) if with_roles else None
    return CapabilityService(ledger, roles=roles)


def _decompose(svc: CapabilityService, children: list[ChildPlan]) -> DecomposeResult:
    return svc.decompose(
        parent_id=uid("M"), revision=REV, actor_employee_id="mgr", children=children
    )


def _assignee(ledger: Ledger, result: DecomposeResult, label: str) -> str | None:
    task = ledger.tasks.get(result.child_ids[label])
    return None if task is None else task.assignee_employee_id


def _submit(svc: CapabilityService, child: ChildPlan, *, revision: str) -> SubmitTaskResult:
    return svc.submit_one(
        parent_id=uid("M"), revision=revision, actor_employee_id="mgr", child=child
    )


def _reroute_destinations(ledger: Ledger) -> tuple[str, ...]:
    destinations: list[str] = []
    for activity in ledger.activity.all():
        raw = activity.payload.get("capability_reroute")
        if not isinstance(raw, list):
            continue
        for item in raw:
            if isinstance(item, dict):
                destination = item.get("to")
                if isinstance(destination, str):
                    destinations.append(destination)
    return tuple(destinations)


def test_delivery_child_reroutes_from_wrong_craft_to_matched_report(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")))
    result = _decompose(
        svc,
        [ChildPlan(label="api", intent="implement the REST API endpoint", assignee="dana")],
    )
    # 'implement the REST API endpoint' is CODE; dana (analyst) is ANALYSIS-native → route to bob.
    assert _assignee(ledger, result, "api") == "bob"
    assert _reroute_destinations(ledger) == ("bob",)


def test_in_craft_assignment_is_left_untouched(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")))
    result = _decompose(
        svc,
        [
            ChildPlan(
                label="study",
                intent="analyze the churn data and quantify the drivers",
                assignee="dana",
            )
        ],
    )
    # ANALYSIS work to the analyst is in-craft — never re-routed.
    assert _assignee(ledger, result, "study") == "dana"
    assert _reroute_destinations(ledger) == ()


def test_ambiguous_intent_is_left_untouched(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")))
    result = _decompose(
        svc, [ChildPlan(label="misc", intent="handle the follow-up", assignee="dana")]
    )
    # No strong deliverable cue → ROLE_DEFAULT → the manager's pick stands (F1 judges it in-craft).
    assert _assignee(ledger, result, "misc") == "dana"


def test_reroute_skipped_when_no_better_report_exists(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("ella", "analyst")))
    result = _decompose(
        svc, [ChildPlan(label="api", intent="implement the REST API endpoint", assignee="dana")]
    )
    # No engineer on the pod — someone has to do it; keep the manager's pick, don't block the work.
    assert _assignee(ledger, result, "api") == "dana"


def test_delegation_child_is_not_rerouted(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")))
    # A delegation child is a sub-lead assignment (managing a nested team), not craft work the child
    # produces — the router leaves it exactly as the manager chose (verified at the routing seam,
    # since a full nested-delegation decompose needs sub-lead grants orthogonal to this behaviour).
    routed = svc._capability_route(
        [
            ChildPlan(
                label="sub",
                intent="implement the REST API endpoint",
                assignee="dana",
                execution_mode=ExecutionMode.DELEGATION,
                can_subdelegate=True,
            )
        ],
        manager_id="mgr",
    )
    assert routed.children[0].assignee == "dana"
    assert routed.reroutes == ()


def test_routing_off_without_a_registry_keeps_the_managers_pick(ledger: Ledger) -> None:
    svc = _service(
        ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")), with_roles=False
    )
    result = _decompose(
        svc, [ChildPlan(label="api", intent="implement the REST API endpoint", assignee="dana")]
    )
    # No registry injected → routing is inert (back-compat for the non-decompose CapabilityService callers).
    assert _assignee(ledger, result, "api") == "dana"


def test_reroute_does_not_launder_a_non_report_assignee(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("bob", "backend_engineer"),))
    ledger.employees.create(Employee(id="eve", name="Eve", role="analyst"))
    result = _decompose(
        svc, [ChildPlan(label="api", intent="implement the REST API endpoint", assignee="eve")]
    )
    # eve is not a report — rewriting her to bob would launder an unauthorized assignee.
    assert result.unknown_assignees == ("eve",)
    assert result.child_ids == {}
    assert _reroute_destinations(ledger) == ()


def test_reroute_picks_matched_report_by_id_not_load(ledger: Ledger) -> None:
    svc = _service(
        ledger,
        reports=(("dana", "analyst"), ("cal", "backend_engineer"), ("bob", "backend_engineer")),
    )
    ledger.tasks.submit(
        Task(
            id=uid("busy"),
            intent="busy work",
            status=TaskStatus.TODO,
            assignee_employee_id="bob",
        )
    )
    result = _decompose(
        svc, [ChildPlan(label="api", intent="implement the REST API endpoint", assignee="dana")]
    )
    # bob is busy and cal is idle, but the policy is id-stable (bob < cal) so the fingerprint does not
    # depend on load.
    assert _assignee(ledger, result, "api") == "bob"


def test_submit_one_reroutes_from_wrong_craft_to_matched_report(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("dana", "analyst"), ("bob", "backend_engineer")))
    ledger.delegation_contracts.update_status(uid("M"), DelegationContractStatus.INTEGRATING)
    revision = uid("run_mgr_submit")
    ledger.runs.create(
        Run(id=revision, employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING)
    )
    result = _submit(
        svc,
        ChildPlan(label="api", intent="implement the REST API endpoint", assignee="dana"),
        revision=revision,
    )
    assert result.authority_denied is None
    assert result.child_id is not None
    task = ledger.tasks.get(result.child_id)
    assert task is not None
    assert task.assignee_employee_id == "bob"


_CODE_INTENT = "implement the REST API endpoint"


def test_declared_doc_on_pm_with_code_shaped_intent_is_not_rerouted(ledger: Ledger) -> None:
    """A declared OutcomeKind is the manager's assignment — do not rewrite it from intent cues."""
    svc = _service(ledger, reports=(("pam", "pm"), ("bob", "backend_engineer")))
    result = _decompose(
        svc,
        [
            ChildPlan(
                label="spec",
                intent=_CODE_INTENT,
                assignee="pam",
                outcome_kind=OutcomeKind.DOC,
            )
        ],
    )
    assert result.outcome_mismatches == ()
    assert result.authority_denied is None
    assert _assignee(ledger, result, "spec") == "pam"
    assert _reroute_destinations(ledger) == ()


def test_undeclared_code_shaped_intent_on_pm_still_reroutes(ledger: Ledger) -> None:
    """#74 routing remains for undeclared children — a pm handed CODE work is rewritten."""
    svc = _service(ledger, reports=(("pam", "pm"), ("bob", "backend_engineer")))
    result = _decompose(
        svc,
        [ChildPlan(label="api", intent=_CODE_INTENT, assignee="pam")],
    )
    assert _assignee(ledger, result, "api") == "bob"
    assert _reroute_destinations(ledger) == ("bob",)


def test_submit_one_declared_doc_on_pm_with_code_shaped_intent_is_not_rerouted(
    ledger: Ledger,
) -> None:
    svc = _service(ledger, reports=(("pam", "pm"), ("bob", "backend_engineer")))
    ledger.delegation_contracts.update_status(uid("M"), DelegationContractStatus.INTEGRATING)
    revision = uid("run_mgr_submit_doc")
    ledger.runs.create(
        Run(id=revision, employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING)
    )
    result = _submit(
        svc,
        ChildPlan(
            label="spec",
            intent=_CODE_INTENT,
            assignee="pam",
            outcome_kind=OutcomeKind.DOC,
        ),
        revision=revision,
    )
    assert result.outcome_mismatches == ()
    assert result.authority_denied is None
    assert result.child_id is not None
    task = ledger.tasks.get(result.child_id)
    assert task is not None
    assert task.assignee_employee_id == "pam"
    assert _reroute_destinations(ledger) == ()


def test_submit_one_undeclared_code_shaped_intent_on_pm_still_reroutes(ledger: Ledger) -> None:
    svc = _service(ledger, reports=(("pam", "pm"), ("bob", "backend_engineer")))
    ledger.delegation_contracts.update_status(uid("M"), DelegationContractStatus.INTEGRATING)
    revision = uid("run_mgr_submit_code")
    ledger.runs.create(
        Run(id=revision, employee_id="mgr", task_id=uid("M"), status=RunStatus.RUNNING)
    )
    result = _submit(
        svc,
        ChildPlan(label="api", intent=_CODE_INTENT, assignee="pam"),
        revision=revision,
    )
    assert result.authority_denied is None
    assert result.child_id is not None
    task = ledger.tasks.get(result.child_id)
    assert task is not None
    assert task.assignee_employee_id == "bob"
