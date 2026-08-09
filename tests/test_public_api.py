"""Pin the public API surface (spec 10 §3).

``chorus/__init__.py`` is the contract. If a symbol disappears or shows up
without being intentionally added to ``EXPECTED_PUBLIC_API`` below, this test
fails and a changelog entry is required.
"""

from __future__ import annotations

import chorus

EXPECTED_PUBLIC_API: frozenset[str] = frozenset(
    {
        # facade
        "Chorus",
        "Caps",
        # low-level grouped surfaces (spec 14 §2.2) — reached via org.<group>
        "BudgetsFacade",
        "DodFacade",
        "GovernanceFacade",
        "InspectFacade",
        "RoutinesFacade",
        "TrustFacade",
        "WorkforceFacade",
        "HireRequest",
        # roles
        "Role",
        "RoleManifest",
        "RolePlugin",
        "RoutineDeclaration",
        "default_roles",
        # ledger
        "Task",
        "TaskStatus",
        "TaskPriority",
        "ExecPlan",
        "Employee",
        # heartbeat
        "Wake",
        "WakeReason",
        "TickReport",
        # cron / routines
        "Routine",
        "RoutineConcurrency",
        "RoutineCatchUp",
        "RoutineTarget",
        "RoutineStatus",
        "parse_cron",
        "Schedule",
        "Weekday",
        # outcomes (DoD)
        "Verifier",
        "Command",
        "AgentReview",
        "HumanApproval",
        # governance (spec 14 §5.1)
        "Approval",
        "ApprovalDecision",
        "ApprovalGate",
        # budgets (spec 14 §5.2)
        "BudgetScope",
        "BudgetWindow",
        # trust (spec 14 §5.3)
        "TrustPreset",
        # events
        "Event",
        "EventKind",
        # read model
        "WorkforceStatus",
        "TaskView",
        "TaskThreadView",
        "EmployeeView",
        "RunView",
        "IncidentView",
        "RoutineView",
        "ScrumPacketView",
        "OrgObservabilityReport",
        # errors
        "ChorusError",
        "InvalidIntake",
        "UnknownEmployee",
        "OrgInvariantViolation",
        "RolePluginInvalid",
        "RolePluginConflict",
        # metadata
        "__version__",
    }
)


def test_all_matches_expected() -> None:
    assert frozenset(chorus.__all__) == EXPECTED_PUBLIC_API


def test_module_exposes_all() -> None:
    exposed = set(dir(chorus))
    missing = EXPECTED_PUBLIC_API - exposed
    assert not missing, f"declared in __all__ but not present on module: {sorted(missing)}"


def test_version_is_string() -> None:
    assert isinstance(chorus.__version__, str)
    assert chorus.__version__.count(".") >= 2
