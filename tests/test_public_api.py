"""Pin the public API surface (spec 10 §3).

``chorus/__init__.py`` is the contract. If a symbol disappears or shows up
without being intentionally added to ``EXPECTED_PUBLIC_API`` below, this test
fails and a changelog entry is required.
"""

from __future__ import annotations

import chorus

EXPECTED_PUBLIC_API: frozenset[str] = frozenset({
    # facade
    "Chorus", "Caps",
    # roles
    "Role", "RoleManifest", "RolePlugin", "default_roles",
    # ledger
    "Task", "TaskStatus", "ExecPlan", "Employee",
    # heartbeat
    "Wake", "WakeReason", "TickReport",
    # cron
    "Routine", "parse_cron",
    # outcomes (DoD)
    "Verifier", "Command", "AgentReview", "HumanApproval",
    # events
    "Event", "EventKind",
    # read model
    "WorkforceStatus", "TaskView", "EmployeeView", "RunView", "IncidentView",
    # errors
    "ChorusError", "InvalidIntake", "UnknownEmployee", "OrgInvariantViolation",
    "RolePluginInvalid", "RolePluginConflict", "BudgetBlocked", "PackageImportError",
    # metadata
    "__version__",
})


def test_all_matches_expected() -> None:
    assert frozenset(chorus.__all__) == EXPECTED_PUBLIC_API


def test_module_exposes_all() -> None:
    exposed = set(dir(chorus))
    missing = EXPECTED_PUBLIC_API - exposed
    assert not missing, f"declared in __all__ but not present on module: {sorted(missing)}"


def test_version_is_string() -> None:
    assert isinstance(chorus.__version__, str)
    assert chorus.__version__.count(".") >= 2
