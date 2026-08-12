"""Projection checks for reports / runtime / lattice wake on the TCP."""

from __future__ import annotations

from chorus.context import (
    LatticeWake,
    OperatingEnvironment,
    operating_environment_from_platform,
    project_employee_wake,
    project_reports,
    project_standalone_wake,
    project_task_context,
)
from chorus.ledger import Task
from chorus.outcomes import PlatformInfo
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee


def test_project_task_context_folds_optional_wake_fields() -> None:
    ledger = open_test_ledger()
    try:
        employee = Employee(id="ada", name="Ada", role="backend_engineer")
        report = Employee(id="bob", name="Bob", role="backend_engineer", reports_to="ada")
        ledger.employees.create(employee)
        ledger.employees.create(report)
        task = ledger.tasks.submit(Task(id=uid("t1"), intent="ship", assignee_employee_id="ada"))
        runtime = OperatingEnvironment("Linux (6)", "/bin/sh", ("Python 3.12",))
        wake = LatticeWake(True, "gate open teaser")

        packet = project_task_context(
            ledger,
            task_id=task.id,
            employee=employee,
            include_reports=True,
            runtime=runtime,
            lattice_wake=wake,
        )

        assert packet.reports == (project_reports(ledger, manager_id="ada")[0],)
        assert packet.runtime is runtime
        assert packet.lattice_wake is wake
    finally:
        ledger.close()


def test_project_task_context_defaults_optional_fields_empty() -> None:
    ledger = open_test_ledger()
    try:
        employee = Employee(id="ada", name="Ada", role="backend_engineer")
        ledger.employees.create(employee)
        task = ledger.tasks.submit(Task(id=uid("t1"), intent="ship", assignee_employee_id="ada"))

        packet = project_task_context(ledger, task_id=task.id, employee=employee)

        assert packet.reports == ()
        assert packet.runtime is None
        assert packet.lattice_wake is None
    finally:
        ledger.close()


def test_project_employee_and_standalone_wake() -> None:
    ledger = open_test_ledger()
    try:
        employee = Employee(id="ada", name="Ada", role="backend_engineer")
        ledger.employees.create(employee)
        runtime = OperatingEnvironment("Linux (6)", "/bin/sh", ("Python 3.12",))
        wake = LatticeWake(True, "teaser")

        with_ledger = project_employee_wake(
            ledger, employee=employee, include_reports=True, runtime=runtime, lattice_wake=wake
        )
        alone = project_standalone_wake(
            employee_id="ada", runtime=runtime, lattice_wake=wake
        )

        assert with_ledger.task_id == "employee:ada"
        assert alone.task_id == "employee:ada"
        assert alone.runtime is runtime
        assert alone.lattice_wake is wake
    finally:
        ledger.close()


def test_operating_environment_from_platform_maps_fields() -> None:
    env = operating_environment_from_platform(
        PlatformInfo(
            os_name="Darwin",
            os_release="25",
            shell="/bin/sh",
            python_version="3.12.0",
            node_version="v22.0.0",
            npm_version="10.0.0",
            playwright_browsers_cached=True,
        )
    )
    assert env.os_label == "Darwin (25)"
    assert env.shell == "/bin/sh"
    assert "Python 3.12.0" in env.path_runtimes
    assert "Node.js v22.0.0" in env.path_runtimes
