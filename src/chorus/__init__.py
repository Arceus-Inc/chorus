"""chorus — an SDK for an org of agents that completes one sprint, built on dream.

The public API is exactly what this module re-exports; ``tests/test_public_api.py``
pins it so a refactor can't silently change the surface (spec 10 §3). Everything
in ``_``-prefixed modules is private and may change at any time.

    dream      one task        →  the employee (plan → sprint → evaluate loop)
    chorus     one sprint      →  the org of employees that do durable work  ← here
    horizon    one company     →  strategy / OKRs / direction
    lattice    the people      →  employee growth + memory consolidation

chorus depends on dream; nothing depends sideways (spec 00 §5).
"""

from __future__ import annotations

from chorus.budgets import BudgetWindow
from chorus.cron import Schedule, Weekday, parse_cron
from chorus.errors import (
    BudgetBlocked,
    ChorusError,
    InvalidIntake,
    OrgInvariantViolation,
    PackageImportError,
    RolePluginConflict,
    RolePluginInvalid,
    UnknownEmployee,
)
from chorus.events import Event, EventKind
from chorus.facade import Caps, Chorus
from chorus.governance import ApprovalDecision
from chorus.groups import (
    BudgetsFacade,
    DodFacade,
    GovernanceFacade,
    HireRequest,
    InspectFacade,
    RoutinesFacade,
    TrustFacade,
    WorkforceFacade,
)
from chorus.heartbeat import TickReport, Wake, WakeReason
from chorus.ledger import (
    Approval,
    ApprovalGate,
    BudgetScope,
    ExecPlan,
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineStatus,
    RoutineTarget,
    Task,
    TaskPriority,
    TaskStatus,
)
from chorus.observability import (
    EmployeeView,
    IncidentView,
    OrgObservabilityReport,
    RoutineView,
    RunView,
    ScrumPacketView,
    TaskView,
    WorkforceStatus,
)
from chorus.outcomes import AgentReview, Command, HumanApproval, Verifier
from chorus.roles import (
    Role,
    RoleManifest,
    RolePlugin,
    RoutineDeclaration,
    default_roles,
)
from chorus.trust import TrustPreset
from chorus.workforce import Employee

__version__ = "0.1.0"

__all__ = [
    "AgentReview",
    # governance (spec 14 §5.1)
    "Approval",
    "ApprovalDecision",
    "ApprovalGate",
    "BudgetBlocked",
    # budgets (spec 14 §5.2)
    "BudgetScope",
    "BudgetWindow",
    # low-level grouped surfaces (spec 14 §2.2)
    "BudgetsFacade",
    "Caps",
    # facade
    "Chorus",
    # errors
    "ChorusError",
    "Command",
    "DodFacade",
    "Employee",
    "EmployeeView",
    # events
    "Event",
    "EventKind",
    "ExecPlan",
    "GovernanceFacade",
    "HireRequest",
    "HumanApproval",
    "IncidentView",
    "InspectFacade",
    "InvalidIntake",
    "OrgInvariantViolation",
    "OrgObservabilityReport",
    "PackageImportError",
    # roles
    "Role",
    "RoleManifest",
    "RolePlugin",
    "RolePluginConflict",
    "RolePluginInvalid",
    # cron / routines
    "Routine",
    "RoutineCatchUp",
    "RoutineConcurrency",
    "RoutineDeclaration",
    "RoutineStatus",
    "RoutineTarget",
    "RoutineView",
    "RoutinesFacade",
    "RunView",
    "Schedule",
    "ScrumPacketView",
    # ledger
    "Task",
    "TaskPriority",
    "TaskStatus",
    "TaskView",
    "TickReport",
    "TrustFacade",
    "TrustPreset",
    "UnknownEmployee",
    # outcomes (DoD)
    "Verifier",
    # heartbeat
    "Wake",
    "WakeReason",
    "Weekday",
    "WorkforceFacade",
    # read model
    "WorkforceStatus",
    # metadata
    "__version__",
    "default_roles",
    "parse_cron",
]
