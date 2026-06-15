"""Per-aggregate repos (spec 01) — one focused module per table, composed by the facade.

Repos speak intersection SQL over a DB-API connection so the same code runs on SQLite now and
Postgres later (spec 12). The :class:`~chorus.ledger.SqliteLedger` facade wires one of each onto a
shared connection.
"""

from __future__ import annotations

from chorus.ledger.repos.artifacts import ArtifactRepo
from chorus.ledger.repos.dependencies import DependencyCycleError, DependencyRepo
from chorus.ledger.repos.dod import DodRepo
from chorus.ledger.repos.employees import EmployeeRepo
from chorus.ledger.repos.goals import GoalRepo
from chorus.ledger.repos.runs import RunRepo
from chorus.ledger.repos.tasks import TaskRepo
from chorus.ledger.repos.wakes import WakeRepo

__all__ = [
    "ArtifactRepo",
    "DependencyCycleError",
    "DependencyRepo",
    "DodRepo",
    "EmployeeRepo",
    "GoalRepo",
    "RunRepo",
    "TaskRepo",
    "WakeRepo",
]
