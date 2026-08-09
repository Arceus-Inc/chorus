"""Per-aggregate repos (spec 01) — one focused module per table, composed by the facade.

Repos speak intersection SQL over a DB-API connection so the same code runs on SQLite now and
the Postgres store (spec 12 §6). The :class:`~chorus.ledger.Ledger` facade wires one of each onto a
shared connection.
"""

from __future__ import annotations

from chorus.ledger.repos.activity import ActivityRepo
from chorus.ledger.repos.agent_sessions import AgentSessionRepo
from chorus.ledger.repos.approvals import ApprovalRepo
from chorus.ledger.repos.artifact_revisions import ArtifactRevisionRepo
from chorus.ledger.repos.artifacts import ArtifactRepo
from chorus.ledger.repos.budget_incidents import BudgetIncidentRepo
from chorus.ledger.repos.budget_policies import BudgetPolicyRepo
from chorus.ledger.repos.cost_events import CostEventRepo
from chorus.ledger.repos.decisions import ClaimRepo, DecisionRepo
from chorus.ledger.repos.decomposition_claims import DecompositionClaimRepo
from chorus.ledger.repos.delegation_contracts import DelegationContractRepo
from chorus.ledger.repos.dependencies import DependencyCycleError, DependencyRepo
from chorus.ledger.repos.dod import DodRepo
from chorus.ledger.repos.employees import EmployeeRepo
from chorus.ledger.repos.goals import GoalRepo
from chorus.ledger.repos.lattice_selection_seals import (
    LatticeSelectionSealConflictError,
    LatticeSelectionSealRepo,
)
from chorus.ledger.repos.management_profiles import ManagementProfileRepo
from chorus.ledger.repos.messages import MessageRepo
from chorus.ledger.repos.monitors import MonitorRepo
from chorus.ledger.repos.recovery_actions import RecoveryActionRepo
from chorus.ledger.repos.routine_revisions import RoutineRevisionRepo
from chorus.ledger.repos.routine_runs import RoutineRunRepo
from chorus.ledger.repos.routine_triggers import RoutineTriggerRepo
from chorus.ledger.repos.routines import RoutineRepo
from chorus.ledger.repos.runs import RunRepo
from chorus.ledger.repos.skill_revisions import SkillRevisionRepo
from chorus.ledger.repos.skills import SkillRepo
from chorus.ledger.repos.staffing_requests import StaffingRequestRepo
from chorus.ledger.repos.tasks import TaskRepo
from chorus.ledger.repos.teams import TeamMemberRepo, TeamRepo
from chorus.ledger.repos.wakes import WakeRepo
from chorus.ledger.repos.workforce_plans import WorkforcePlanRepo

__all__ = [
    "ActivityRepo",
    "AgentSessionRepo",
    "ApprovalRepo",
    "ArtifactRepo",
    "ArtifactRevisionRepo",
    "BudgetIncidentRepo",
    "BudgetPolicyRepo",
    "ClaimRepo",
    "CostEventRepo",
    "DecisionRepo",
    "DecompositionClaimRepo",
    "DelegationContractRepo",
    "DependencyCycleError",
    "DependencyRepo",
    "DodRepo",
    "EmployeeRepo",
    "GoalRepo",
    "LatticeSelectionSealConflictError",
    "LatticeSelectionSealRepo",
    "ManagementProfileRepo",
    "MessageRepo",
    "MonitorRepo",
    "RecoveryActionRepo",
    "RoutineRepo",
    "RoutineRevisionRepo",
    "RoutineRunRepo",
    "RoutineTriggerRepo",
    "RunRepo",
    "SkillRepo",
    "SkillRevisionRepo",
    "StaffingRequestRepo",
    "TaskRepo",
    "TeamMemberRepo",
    "TeamRepo",
    "WakeRepo",
    "WorkforcePlanRepo",
]
