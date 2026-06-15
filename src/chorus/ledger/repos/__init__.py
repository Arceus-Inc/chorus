"""Per-aggregate repos (spec 01) — one focused module per table, composed by the facade.

Repos speak intersection SQL over a DB-API connection so the same code runs on SQLite now and
Postgres later (spec 12). The :class:`~chorus.ledger.SqliteLedger` facade wires one of each onto a
shared connection.
"""

from __future__ import annotations

from chorus.ledger.repos.activity import ActivityRepo
from chorus.ledger.repos.approvals import ApprovalRepo
from chorus.ledger.repos.artifact_revisions import ArtifactRevisionRepo
from chorus.ledger.repos.artifacts import ArtifactRepo
from chorus.ledger.repos.budget_incidents import BudgetIncidentRepo
from chorus.ledger.repos.budget_policies import BudgetPolicyRepo
from chorus.ledger.repos.cost_events import CostEventRepo
from chorus.ledger.repos.decomposition_claims import DecompositionClaimRepo
from chorus.ledger.repos.dependencies import DependencyCycleError, DependencyRepo
from chorus.ledger.repos.dod import DodRepo
from chorus.ledger.repos.employees import EmployeeRepo
from chorus.ledger.repos.goals import GoalRepo
from chorus.ledger.repos.messages import MessageRepo
from chorus.ledger.repos.monitors import MonitorRepo
from chorus.ledger.repos.recovery_actions import RecoveryActionRepo
from chorus.ledger.repos.runs import RunRepo
from chorus.ledger.repos.tasks import TaskRepo
from chorus.ledger.repos.wakes import WakeRepo

__all__ = [
    "ActivityRepo",
    "ApprovalRepo",
    "ArtifactRepo",
    "ArtifactRevisionRepo",
    "BudgetIncidentRepo",
    "BudgetPolicyRepo",
    "CostEventRepo",
    "DecompositionClaimRepo",
    "DependencyCycleError",
    "DependencyRepo",
    "DodRepo",
    "EmployeeRepo",
    "GoalRepo",
    "MessageRepo",
    "MonitorRepo",
    "RecoveryActionRepo",
    "RunRepo",
    "TaskRepo",
    "WakeRepo",
]
