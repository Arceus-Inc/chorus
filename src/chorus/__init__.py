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

from chorus.cron import parse_cron
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
from chorus.heartbeat import TickReport, Wake, WakeReason
from chorus.ledger import (
    ExecPlan,
    Routine,
    RoutineCatchUp,
    RoutineConcurrency,
    RoutineStatus,
    RoutineTarget,
    Task,
    TaskStatus,
)
from chorus.observability import (
    EmployeeView,
    IncidentView,
    RoutineView,
    RunView,
    TaskView,
    WorkforceStatus,
)
from chorus.outcomes import AgentReview, Command, HumanApproval, Verifier
from chorus.roles import Role, RoleManifest, RolePlugin, default_roles
from chorus.workforce import Employee

__version__ = "0.1.0"

__all__ = [
    "AgentReview",
    "BudgetBlocked",
    "Caps",
    # facade
    "Chorus",
    # errors
    "ChorusError",
    "Command",
    "Employee",
    "EmployeeView",
    # events
    "Event",
    "EventKind",
    "ExecPlan",
    "HumanApproval",
    "IncidentView",
    "InvalidIntake",
    "OrgInvariantViolation",
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
    "RoutineStatus",
    "RoutineTarget",
    "RoutineView",
    "RunView",
    # ledger
    "Task",
    "TaskStatus",
    "TaskView",
    "TickReport",
    "UnknownEmployee",
    # outcomes (DoD)
    "Verifier",
    # heartbeat
    "Wake",
    "WakeReason",
    # read model
    "WorkforceStatus",
    # metadata
    "__version__",
    "default_roles",
    "parse_cron",
]
