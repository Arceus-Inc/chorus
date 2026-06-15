"""The chorus ledger (spec 01).

The DAG of work, the org tree, and the durable rows the scheduler reads. Re-exports dream's
``ExecPlan``/``ExecPlanStatus`` contracts (spec 05) where the seam is shared — a chorus ``Task``
*is* an ``ExecPlan`` made durable. Storage is per-aggregate **repos** behind a ``SqliteLedger``
facade, applied via an **applied-migration-set** runner (spec 01 §schema-versioning, spec 12).
"""

from __future__ import annotations

from dream.contracts import ExecPlan, ExecPlanLedger, ExecPlanStatus

from chorus.ledger._ledger import Ledger, SqliteLedger
from chorus.ledger._migrations import (
    LedgerAheadError,
    Migration,
    MigrationDriftError,
    MigrationError,
    MigrationRunner,
)
from chorus.ledger._models import (
    Artifact,
    ArtifactType,
    Dod,
    DodStatus,
    Goal,
    GoalLevel,
    OriginKind,
    Run,
    RunStatus,
    Task,
    TaskDependency,
    TaskPriority,
    TaskStatus,
    Wake,
    WakeReason,
    WakeStatus,
)
from chorus.ledger.migrations import MIGRATIONS
from chorus.ledger.repos import (
    ArtifactRepo,
    DependencyCycleError,
    DependencyRepo,
    DodRepo,
    EmployeeRepo,
    GoalRepo,
    RunRepo,
    TaskRepo,
    WakeRepo,
)

__all__ = [
    "MIGRATIONS",
    "Artifact",
    "ArtifactRepo",
    "ArtifactType",
    "DependencyCycleError",
    "DependencyRepo",
    "Dod",
    "DodRepo",
    "DodStatus",
    "EmployeeRepo",
    "ExecPlan",
    "ExecPlanLedger",
    "ExecPlanStatus",
    "Goal",
    "GoalLevel",
    "GoalRepo",
    "Ledger",
    "LedgerAheadError",
    "Migration",
    "MigrationDriftError",
    "MigrationError",
    "MigrationRunner",
    "OriginKind",
    "Run",
    "RunRepo",
    "RunStatus",
    "SqliteLedger",
    "Task",
    "TaskDependency",
    "TaskPriority",
    "TaskRepo",
    "TaskStatus",
    "Wake",
    "WakeReason",
    "WakeRepo",
    "WakeStatus",
]
