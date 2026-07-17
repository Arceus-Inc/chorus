"""Deterministic specialist lead selection for delegated intake."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from dream.contracts.delegation import (
    DelegatedWorkRequest,
    StaffingBlocked,
    StaffingRequirement,
)

from chorus.ledger import (
    BudgetPolicy,
    BudgetScope,
    CostEvent,
    ManagementProfile,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.lifecycle import LeadSelector
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 7, 13, 12, tzinfo=UTC)


def _candidate(
    ledger: SqliteLedger,
    employee_id: str,
    *,
    profession: str = "architect",
    report_professions: tuple[str, ...] = ("engineer",),
) -> Employee:
    lead = ledger.employees.create(
        Employee(id=employee_id, name=employee_id.title(), role=profession)
    )
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id=lead.id,
            granted_by_user_id="user-admin",
            active=True,
            can_lead=True,
            max_delegation_depth=2,
            max_team_size=5,
            allowed_professions=tuple(dict.fromkeys(("engineer", "designer", *report_professions))),
            version=1,
        )
    )
    for index, report_profession in enumerate(report_professions):
        ledger.employees.create(
            Employee(
                id=f"{employee_id}-report-{index}",
                name=f"{employee_id.title()} Report {index}",
                role=report_profession,
                reports_to=lead.id,
            )
        )
    persisted = ledger.employees.get(lead.id)
    assert persisted is not None
    return persisted


def _request(*, preferred_lead: str | None = None) -> DelegatedWorkRequest:
    return DelegatedWorkRequest(
        intent="Ship M8",
        goal_id="goal-8",
        requirements=(StaffingRequirement("engineer"),),
        preferred_lead=preferred_lead,
        origin_fingerprint="goal-8:v1",
    )


def _selector(ledger: SqliteLedger) -> LeadSelector:
    return LeadSelector(ledger, company_id="company", clock=lambda: _NOW)


def test_valid_preferred_lead_wins_over_automatic_ranking(ledger: SqliteLedger) -> None:
    _candidate(ledger, "alpha")
    preferred = _candidate(ledger, "zulu")

    selected = _selector(ledger).select(_request(preferred_lead=preferred.id))

    assert selected == preferred


def test_no_eligible_lead_returns_typed_staffing_blocked(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="unprofiled", name="Unprofiled", role="engineer"))

    selected = _selector(ledger).select(_request())

    assert selected == StaffingBlocked(
        goal_id="goal-8",
        reason="no invokable lead satisfies profile, line, team-size, and budget constraints",
    )
    assert ledger.tasks.all() == []


def test_profession_fit_precedes_employee_id_tiebreak(ledger: SqliteLedger) -> None:
    _candidate(ledger, "alpha", profession="designer")
    matching = _candidate(ledger, "zulu", profession="engineer")

    assert _selector(ledger).select(_request()) == matching


def test_lower_observed_load_precedes_budget_headroom(ledger: SqliteLedger) -> None:
    busy = _candidate(ledger, "alpha")
    available = _candidate(ledger, "zulu")
    ledger.tasks.submit(
        Task(
            id="busy-task",
            intent="Existing work",
            status=TaskStatus.TODO,
            assignee_employee_id=busy.id,
        )
    )
    ledger.budget_policies.create(
        BudgetPolicy(
            id="busy-budget",
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=busy.id,
            amount=100_000,
        )
    )
    ledger.budget_policies.create(
        BudgetPolicy(
            id="available-budget",
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=available.id,
            amount=1_000,
        )
    )

    assert _selector(ledger).select(_request()) == available


def test_greater_budget_headroom_precedes_employee_id_tiebreak(
    ledger: SqliteLedger,
) -> None:
    _candidate(ledger, "alpha")
    greater_headroom = _candidate(ledger, "zulu")
    for employee_id, amount in (("alpha", 1_000), ("zulu", 2_000)):
        ledger.budget_policies.create(
            BudgetPolicy(
                id=f"budget-{employee_id}",
                scope_type=BudgetScope.EMPLOYEE,
                scope_id=employee_id,
                amount=amount,
            )
        )

    assert _selector(ledger).select(_request()) == greater_headroom


def test_budget_blocked_candidate_is_excluded(ledger: SqliteLedger) -> None:
    blocked = _candidate(ledger, "alpha", profession="engineer")
    fallback = _candidate(ledger, "zulu")
    ledger.budget_policies.create(
        BudgetPolicy(
            id="blocked-budget",
            scope_type=BudgetScope.EMPLOYEE,
            scope_id=blocked.id,
            amount=100,
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id="blocked-spend",
            employee_id=blocked.id,
            provider="test",
            model="test",
            cost_cents=100,
            occurred_at=_NOW,
        )
    )

    assert _selector(ledger).select(_request()) == fallback


def test_equal_candidates_use_stable_employee_id_tiebreak(ledger: SqliteLedger) -> None:
    selected = _candidate(ledger, "alpha")
    _candidate(ledger, "zulu")

    assert _selector(ledger).select(_request()) == selected


def test_hierarchical_requirements_select_shallow_ceo_over_leaf_specialists(
    ledger: SqliteLedger,
) -> None:
    ceo = ledger.employees.create(Employee(id="ceo", name="CEO", role="ceo"))
    ledger.management_profiles.upsert(
        ManagementProfile(
            employee_id="ceo",
            granted_by_user_id="founder",
            active=True,
            can_lead=True,
            can_subdelegate=True,
            max_delegation_depth=2,
            max_team_size=3,
            allowed_professions=("pm", "backend_engineer"),
        )
    )
    ledger.employees.create(
        Employee(id="product-lead", name="Product Lead", role="pm", reports_to="ceo")
    )
    ledger.employees.create(
        Employee(
            id="engineering-lead",
            name="Engineering Lead",
            role="backend_engineer",
            reports_to="ceo",
        )
    )
    ledger.employees.create(
        Employee(
            id="designer",
            name="Designer",
            role="designer",
            reports_to="product-lead",
        )
    )
    ledger.employees.create(
        Employee(
            id="frontend",
            name="Frontend",
            role="frontend_engineer",
            reports_to="engineering-lead",
        )
    )
    ledger.employees.create(
        Employee(
            id="backend",
            name="Backend",
            role="backend_engineer",
            reports_to="engineering-lead",
        )
    )
    request = DelegatedWorkRequest(
        intent="Ship feedback triage",
        goal_id="goal-product",
        lead_professions=("ceo",),
        requirements=(
            StaffingRequirement("designer", coverage="subtree", outcome_area="product"),
            StaffingRequirement(
                "frontend_engineer", coverage="subtree", outcome_area="engineering"
            ),
            StaffingRequirement("backend_engineer", coverage="subtree", outcome_area="engineering"),
        ),
    )

    selected = _selector(ledger).select(request)
    assert isinstance(selected, Employee) and selected.id == ceo.id


def test_explicit_lead_profession_selects_functional_owner(
    ledger: SqliteLedger,
) -> None:
    _candidate(ledger, "product-lead", profession="pm")
    engineering = _candidate(
        ledger,
        "engineering-lead",
        profession="backend_engineer",
        report_professions=("frontend_engineer",),
    )
    request = DelegatedWorkRequest(
        intent="Build the interface",
        goal_id="goal-engineering",
        lead_professions=("backend_engineer",),
        requirements=(StaffingRequirement("frontend_engineer"),),
    )

    assert _selector(ledger).select(request) == engineering
