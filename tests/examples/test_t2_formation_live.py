"""T2 live-run report contracts: governed formation without delivery execution."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "t2_formation_live.py"


def _load_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("t2_formation_live", _EXAMPLE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _passing_snapshot(module):  # type: ignore[no-untyped-def]
    employees = (
        module.EmployeeView("ceo", "ceo", None),
        module.EmployeeView("engineering-lead", "backend_engineer", "ceo"),
        module.EmployeeView("backend-1", "backend_engineer", "engineering-lead"),
        module.EmployeeView("backend-2", "backend_engineer", "engineering-lead"),
        module.EmployeeView("backend-3", "backend_engineer", "engineering-lead"),
        module.EmployeeView("frontend-1", "frontend_engineer", "engineering-lead"),
        module.EmployeeView("frontend-2", "frontend_engineer", "engineering-lead"),
        module.EmployeeView("frontend-3", "frontend_engineer", "engineering-lead"),
    )
    profiles = (
        module.ManagementView("ceo", True, 2, 2, 700_000),
        module.ManagementView("engineering-lead", True, 1, 7, 500_000),
    )
    return module.T2Snapshot(
        ceo_outcome_passed=True,
        plan_status_before="proposed",
        plan_status_after="applied",
        proposed_by_employee_id="ceo",
        decided_by_user_id="founder",
        employees_before=(module.EmployeeView("ceo", "ceo", None),),
        profiles_before=(),
        employees_after=employees,
        profiles_after=profiles,
        proposal_audit_actor="ceo",
        approval_audit_actor="founder",
        employee_budget_allocations_cents=(700_000,) * 7,
        budget_ceiling_cents=700_000,
        task_count=0,
        run_count=0,
        tool_names=("workforce_catalog_read", "workforce_plan_propose", "write_file"),
        tool_use_count=3,
        tool_result_count=3,
        all_tool_results_lossless=True,
        event_count=20,
        trace_count=1,
        secret_redaction_safe=True,
    )


def _check(module, snapshot, name: str):  # type: ignore[no-untyped-def]
    return next(check for check in module.evaluate_invariants(snapshot) if check.name == name)


def test_t2_invariants_accept_governed_parallel_capable_org() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)

    assert all(check.passed for check in module.evaluate_invariants(passing))


def test_t2_invariants_reject_hires_before_human_approval() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    unilateral = module.T2Snapshot(
        **{**passing.__dict__, "employees_before": passing.employees_after}
    )

    assert not _check(module, unilateral, "human-gated formation").passed


def test_t2_invariants_reject_invalid_reporting_authority() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    invalid = tuple(
        module.EmployeeView(employee.id, employee.role, "backend-1")
        if employee.id == "frontend-1"
        else employee
        for employee in passing.employees_after
    )
    bad_authority = module.T2Snapshot(**{**passing.__dict__, "employees_after": invalid})

    assert not _check(module, bad_authority, "reporting authority").passed


def test_t2_invariants_reject_wrong_staffing_shape() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    undersized = module.T2Snapshot(
        **{
            **passing.__dict__,
            "employees_after": tuple(
                employee for employee in passing.employees_after if employee.id != "frontend-3"
            ),
        }
    )

    assert not _check(module, undersized, "parallel-capable org shape").passed


def test_t2_invariants_reject_any_delivery_execution() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)
    executed = module.T2Snapshot(**{**passing.__dict__, "task_count": 1, "run_count": 1})

    assert not _check(module, executed, "no delivery execution").passed


def test_t2_budget_ceiling_applies_to_each_employee_allocation() -> None:
    module = _load_module()
    passing = _passing_snapshot(module)

    assert _check(module, passing, "budget ceiling").passed

    excessive = module.T2Snapshot(
        **{
            **passing.__dict__,
            "employee_budget_allocations_cents": (700_001, *([700_000] * 6)),
        }
    )
    assert not _check(module, excessive, "budget ceiling").passed
