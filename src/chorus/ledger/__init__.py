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
    Activity,
    ActivityVerb,
    Approval,
    ApprovalStatus,
    ApprovalSubjectKind,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    Dod,
    DodStatus,
    Goal,
    GoalLevel,
    Message,
    MessageKind,
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
    ActivityRepo,
    ApprovalRepo,
    ArtifactRepo,
    ArtifactRevisionRepo,
    DependencyCycleError,
    DependencyRepo,
    DodRepo,
    EmployeeRepo,
    GoalRepo,
    MessageRepo,
    RunRepo,
    TaskRepo,
    WakeRepo,
)

__all__ = [
    "MIGRATIONS",
    "Activity",
    "ActivityRepo",
    "ActivityVerb",
    "Approval",
    "ApprovalRepo",
    "ApprovalStatus",
    "ApprovalSubjectKind",
    "Artifact",
    "ArtifactRepo",
    "ArtifactRevision",
    "ArtifactRevisionRepo",
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
    "Message",
    "MessageKind",
    "MessageRepo",
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
