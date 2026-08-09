"""The ledger (spec 01, spec 12 §6) — Postgres, the only store. SQLite is retired.

``Ledger`` opens a psycopg connection (RLS-scoped to a company), bootstraps the checked-in native
per-table schema (``schema/*.sql``, FK-ordered at load) under an advisory lock, wires one repo per
aggregate, and owns the cross-aggregate atomics (``transaction`` batching, ``finalize_beat``, ``create_child``). The kernel
types against this class directly — one driver, no protocol indirection.

Schema versioning: the baseline's checksum is recorded in ``chorus_schema_migrations``. A checksum
mismatch on open means the schema evolved after this database was created — with no released
deployments the correct move is a fresh bootstrap; once deployments exist, authored Postgres
migrations take over from the baseline (the applied-set model is already in place for them).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from chorus.ids import mint_id
from chorus.ledger._connection import LedgerConnection
from chorus.ledger._errors import LedgerIntegrityError
from chorus.ledger._migrations import (
    LedgerAheadError,
    Migration,
    MigrationDriftError,
    load_migrations,
    split_statements,
)
from chorus.ledger._models import (
    DecompositionClaim,
    DecompositionStatus,
    DodStatus,
    ExecutionMode,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)
from chorus.ledger.repos import (
    ActivityRepo,
    AgentConfigRevisionRepo,
    AgentSessionRepo,
    ApprovalRepo,
    ArtifactRepo,
    ArtifactRevisionRepo,
    BudgetIncidentRepo,
    BudgetPolicyRepo,
    ClaimRepo,
    CostEventRepo,
    DecisionRepo,
    DecompositionClaimRepo,
    DelegationContractRepo,
    DependencyRepo,
    DodRepo,
    EmployeeRepo,
    EvalCaseRepo,
    EvalRunRepo,
    EvalSuiteRepo,
    GoalRepo,
    ManagementProfileRepo,
    MessageRepo,
    MonitorRepo,
    RecoveryActionRepo,
    ReflectionApplicationAuthorizationRepo,
    ReflectionProposalRepo,
    ReflectionProposalReviewRepo,
    RolloutRepo,
    RoutineRepo,
    RoutineRevisionRepo,
    RoutineRunRepo,
    RoutineTriggerRepo,
    RunRepo,
    SkillRepo,
    SkillRevisionRepo,
    StaffingRequestRepo,
    TaskRepo,
    TeamMemberRepo,
    TeamRepo,
    WakeRepo,
    WorkforcePlanRepo,
)

_BASELINE_ID = "0001_baseline"
_ADVISORY_LOCK_KEY = 0x43484F52  # 'CHOR' — serialises concurrent bootstrap attempts

_SCHEMA_MIGRATIONS_DDL = """
CREATE TABLE IF NOT EXISTS chorus_schema_migrations (
    id         text PRIMARY KEY,
    checksum   text NOT NULL,
    applied_at timestamptz NOT NULL
)
"""


class SchemaDriftError(RuntimeError):
    """The baseline schema changed after this database was baselined (checksum mismatch)."""


_CREATE_TABLE = re.compile(r"CREATE TABLE (\w+)", re.I)
_REFERENCES = re.compile(r"REFERENCES\s+(\w+)\s*\(", re.I)


def _dependency_order(tables: dict[str, str]) -> list[str]:
    """Table names topologically sorted by their REFERENCES edges (Kahn; name-stable).

    Postgres validates FK targets at CREATE TABLE, so per-table files can't just load
    alphabetically. The routine⇄routine_revision reference cycle is already broken in the DDL
    itself (one edge is an ALTER TABLE ADD FOREIGN KEY, sequenced after the tables)."""
    deps: dict[str, set[str]] = {}
    for name, statement in tables.items():
        targets = {match.group(1) for match in _REFERENCES.finditer(statement)}
        deps[name] = {target for target in targets if target != name and target in tables}
    ordered: list[str] = []
    remaining = dict(deps)
    while remaining:
        ready = sorted(name for name, waiting in remaining.items() if waiting <= set(ordered))
        if not ready:
            raise ValueError(f"circular REFERENCES among ledger tables: {sorted(remaining)}")
        ordered.extend(ready)
        for name in ready:
            del remaining[name]
    return ordered


def postgres_ddl() -> list[str]:
    """Every ledger DDL statement from the per-table ``schema/*.sql`` files (Postgres-native),
    sequenced for a fresh database: tables in FK-dependency order, then deferred FK constraints,
    RLS, and indexes."""
    tables: dict[str, str] = {}
    trailing: list[str] = []  # ALTERs / policies / indexes — valid only after their tables exist
    schema_dir = files("chorus.ledger.schema")
    for entry in sorted(schema_dir.iterdir(), key=lambda item: item.name):
        if not entry.name.endswith(".sql"):
            continue
        for statement in split_statements(entry.read_text()):
            match = _CREATE_TABLE.match(statement)
            if match is not None:
                tables[match.group(1)] = statement
            else:
                trailing.append(statement)
    return [tables[name] for name in _dependency_order(tables)] + trailing


def ledger_table_names() -> list[str]:
    """Every ledger table name, creation order — for deployments that grant a runtime role."""
    names: list[str] = []
    for statement in postgres_ddl():
        if statement.upper().startswith("CREATE TABLE "):
            names.append(statement.split(None, 2)[2].split("(", 1)[0].strip())
    return names


def baseline() -> tuple[str, str, list[str]]:
    """(baseline id, checksum, DDL statements) — for deployments that apply the schema in their
    own migration stream (e.g. podium's alembic). Writing the returned id+checksum into
    ``chorus_schema_migrations`` makes every later :meth:`Ledger.open` probe and skip DDL."""
    statements = postgres_ddl()
    digest = hashlib.sha256()
    for statement in statements:
        digest.update(statement.encode("utf-8"))
        digest.update(b"\x00")
    return _BASELINE_ID, digest.hexdigest(), statements


def _wake_id() -> str:
    return mint_id()


class Ledger:
    """The durable store the scheduler reads and writes — repos wired over one RLS-scoped
    connection, plus the cross-aggregate atomic operations."""

    def __init__(self, conn: LedgerConnection) -> None:
        self._conn: LedgerConnection = conn
        self._schema_version: str | None = None
        self.employees = EmployeeRepo(conn)
        self.agent_sessions = AgentSessionRepo(conn)
        self.goals = GoalRepo(conn)
        self.tasks = TaskRepo(conn)
        self.management_profiles = ManagementProfileRepo(conn)
        self.teams = TeamRepo(conn)
        self.team_members = TeamMemberRepo(conn)
        self.delegation_contracts = DelegationContractRepo(conn)
        self.decomposition_claims = DecompositionClaimRepo(conn)
        self.dependencies = DependencyRepo(conn)
        self.wakes = WakeRepo(conn)
        self.messages = MessageRepo(conn)
        self.approvals = ApprovalRepo(conn)
        self.decisions = DecisionRepo(conn)
        self.claims = ClaimRepo(conn)
        self.activity = ActivityRepo(conn)
        self.monitors = MonitorRepo(conn)
        self.recovery_actions = RecoveryActionRepo(conn)
        self.routines = RoutineRepo(conn)
        self.routine_revisions = RoutineRevisionRepo(conn)
        self.routine_triggers = RoutineTriggerRepo(conn)
        self.routine_runs = RoutineRunRepo(conn)
        self.runs = RunRepo(conn)
        self.skills = SkillRepo(conn)
        self.skill_revisions = SkillRevisionRepo(conn)
        self.agent_config_revisions = AgentConfigRevisionRepo(conn)
        self.eval_cases = EvalCaseRepo(conn)
        self.eval_suites = EvalSuiteRepo(conn)
        self.eval_runs = EvalRunRepo(conn)
        self.rollouts = RolloutRepo(conn)
        self.reflection_proposals = ReflectionProposalRepo(conn)
        self.reflection_proposal_reviews = ReflectionProposalReviewRepo(conn)
        self.reflection_application_authorizations = ReflectionApplicationAuthorizationRepo(conn)
        self.dod = DodRepo(conn)
        self.artifacts = ArtifactRepo(conn)
        self.artifact_revisions = ArtifactRevisionRepo(conn)
        self.budget_policies = BudgetPolicyRepo(conn)
        self.budget_incidents = BudgetIncidentRepo(conn)
        self.cost_events = CostEventRepo(conn)
        self.workforce_plans = WorkforcePlanRepo(conn)
        self.staffing_requests = StaffingRequestRepo(conn)

    @classmethod
    def open(cls, conninfo: str, *, company_id: str | None = None) -> Ledger:
        """Connect, bootstrap (idempotent, advisory-locked), and wire the repos.

        ``company_id`` pins the session's tenancy context: FORCE RLS scopes every read/write to
        that company and the ``company_id`` DEFAULT stamps every insert. Without it the ledger is
        read-only-empty and write-refusing (fail closed) under a non-superuser role — pass it for
        any real work; omit it only for bootstrap/administrative opens.
        """
        conn = LedgerConnection.connect(conninfo, company_id=company_id)
        ledger = cls(conn)
        try:
            ledger._bootstrap()
            if company_id is not None:
                ledger._seed_system_principals()
        except BaseException:
            # Bootstrap/seed failed after the connection opened — release it so a failing open
            # (e.g. migration drift) cannot leak a slot on every retry and exhaust the pool.
            ledger.close()
            raise
        return ledger

    def _seed_system_principals(self) -> None:
        """The built-in non-workforce actors, seeded once per company (idempotent).

        Lived in a schema migration in the SQLite era; with company-scoped principals the seed
        needs the session's company context, so it runs on the first company-scoped open.
        """
        self._conn.execute(
            "INSERT INTO system_principal (id, kind, display_name, purpose, created_at) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT (company_id, id) DO NOTHING",
            (
                "system-verifier",
                "verification",
                "System Verifier",
                "Independent read-only verification of employee-authored work",
                "1970-01-01T00:00:00+00:00",
            ),
        )
        self._conn.commit()

    def _bootstrap(self) -> None:
        import psycopg

        baseline_id, checksum, statements = baseline()
        pg = self._conn._pg
        # One explicit transaction for the whole bootstrap; the advisory lock is transaction-scoped,
        # so two processes opening together serialise and the loser sees the recorded baseline.
        with pg.transaction():
            pg.execute("SELECT pg_advisory_xact_lock(%s)", (_ADVISORY_LOCK_KEY,))
            # Probe before creating: a non-owner runtime role (SELECT-granted, no schema CREATE)
            # must be able to open an already-bootstrapped database. The savepoint contains the
            # UndefinedTable error on a genuinely fresh database.
            try:
                with pg.transaction():
                    row = pg.execute(
                        "SELECT checksum FROM chorus_schema_migrations WHERE id = %s",
                        (baseline_id,),
                    ).fetchone()
            except psycopg.errors.UndefinedTable:
                row = None
                pg.execute(_SCHEMA_MIGRATIONS_DDL)  # fresh database — needs an owner/DDL role
            if row is not None:
                if row["checksum"] != checksum:
                    raise SchemaDriftError(
                        "the ledger baseline changed after this database was baselined; "
                        "author a migration in chorus/ledger/migrations/ instead of editing "
                        "the baseline (schema/*.sql is frozen once databases exist)"
                    )
            else:
                for statement in statements:
                    pg.execute(statement)
                pg.execute(
                    "INSERT INTO chorus_schema_migrations (id, checksum, applied_at) "
                    "VALUES (%s, %s, %s)",
                    (baseline_id, checksum, datetime.now(UTC)),
                )
            shipped = load_migrations()
            self._apply_pending_migrations(pg, baseline_id, shipped)
        # The display version: the newest applied id (the baseline when no deltas shipped yet).
        self._schema_version = shipped[-1].id if shipped else baseline_id

    def _apply_pending_migrations(
        self, pg: Any, baseline_id: str, shipped: list[Migration]
    ) -> None:
        """Apply the authored delta stream (applied-set model) inside the bootstrap transaction.

        Runs under the advisory lock, so concurrent opens serialise. Refuses a database that is
        AHEAD of the SDK (applied id we do not ship) and a shipped migration whose checksum
        DRIFTED from its applied row — both mean human intervention, never guessing.
        """
        applied = {
            row["id"]: row["checksum"]
            for row in pg.execute("SELECT id, checksum FROM chorus_schema_migrations").fetchall()
        }
        shipped_ids = {migration.id for migration in shipped} | {baseline_id}
        ahead = sorted(set(applied) - shipped_ids)
        if ahead:
            raise LedgerAheadError(
                f"database has applied migrations this SDK does not ship: {', '.join(ahead)} — "
                "upgrade the SDK"
            )
        for migration in shipped:
            recorded = applied.get(migration.id)
            if recorded is not None:
                if recorded != migration.checksum:
                    raise MigrationDriftError(
                        f"migration {migration.id} was edited after it was applied "
                        "(deployed migrations are immutable — author a new migration)"
                    )
                continue
            for statement in migration.statements():
                pg.execute(statement)
            pg.execute(
                "INSERT INTO chorus_schema_migrations (id, checksum, applied_at) "
                "VALUES (%s, %s, %s)",
                (migration.id, migration.checksum, datetime.now(UTC)),
            )

    def schema_version(self) -> str | None:
        return self._schema_version

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Batch every repo write in the block into one transaction (atomic commit / rollback).

        Repo methods defer their per-call commits while this is active; the outermost block commits
        once on success or rolls back if *any* block — including a nested one whose exception was
        caught by surrounding code — raised. Re-entrant: nested blocks are one transaction.
        """
        conn = self._conn
        conn._defer_depth += 1
        try:
            yield
        except BaseException:
            conn._tx_aborted = True  # latch so the outermost block can't commit partial writes
            raise
        finally:
            conn._defer_depth -= 1
            if conn._defer_depth == 0:
                aborted = conn._tx_aborted
                conn._tx_aborted = False
                if aborted:
                    conn.rollback()
                else:
                    conn.commit()  # depth back to 0 -> a real commit

    def finalize_beat(
        self,
        *,
        task_id: str,
        run_id: str | None,
        dod_status: DodStatus,
        verdict: dict[str, object] | None = None,
    ) -> list[Wake]:
        """Apply a beat's verdict atomically (spec 01 Cluster F, spec 03 ``fire_downstream_wakes``).

        In one transaction: record the ``dod`` verdict (if the task has a dod row), and — when the
        verdict is ``passed`` — derive ``task.status='done'`` (+ ``completed_at``) and enqueue the
        downstream wakes that let the *next* beat pick up the now-unblocked work (``deps_resolved``
        for newly-unblocked dependents, ``children_done`` for a parent whose last child just landed).
        A non-passed verdict only records the dod result and leaves the task for rework. Returns the
        wakes enqueued.
        """
        with self.transaction():
            dod = self.dod.get_for_task(task_id)
            if dod is not None:
                self.dod.record_verdict(dod.id, dod_status, verdict=verdict, run_id=run_id)
            if dod_status is not DodStatus.PASSED:
                return []
            self.tasks.set_status(task_id, TaskStatus.DONE)
            self._complete_goal_if_root(task_id)
            return self._fire_downstream_wakes(task_id)

    def _complete_goal_if_root(self, task_id: str) -> None:
        """Roll a goal up to ``done`` when its delegation-root task lands ``done``.

        The engine seeds goals ``active`` and never closed them, so a company's roadmap never
        advanced no matter how much work landed. A goal's *top* task — ``parent_id is None``,
        ``execution_mode = DELEGATION``, carrying the ``goal_id`` — reaching ``done`` *is* the goal
        being achieved, so flip the goal here (atomically, inside the finalize transaction). Only the
        goal-root flips it; a mid-tree child landing ``done`` carries the same ``goal_id`` but a
        non-null ``parent_id`` and is ignored.
        """
        task = self.tasks.get(task_id)
        if task is None or task.parent_id is not None or task.goal_id is None:
            return
        if task.execution_mode is not ExecutionMode.DELEGATION:
            return
        goal = self.goals.get(task.goal_id)
        if goal is None or goal.status == "done":
            return
        self.goals.update(replace(goal, status="done"))

    def create_child(self, claim_id: str, child: Task) -> DecompositionClaim:
        """Create a decomposition child + record it on the claim in one transaction (spec 02 §4).

        The child ``task`` insert and the ``child_task_ids`` append commit together (or neither), so a
        crash mid-fan-out never leaves a task the claim doesn't know about. **Idempotent on retry**:
        if the child is already recorded on the claim the existing claim is returned unchanged (no
        duplicate-insert), so a resumed fan-out reuses already-created children (spec 02 §4). A sealed
        (non-``in_flight``) claim rejects the child before any task is inserted.
        """
        with self.transaction():
            claim = self.decomposition_claims.get(claim_id)
            if claim is None:
                raise KeyError(claim_id)
            if claim.status is not DecompositionStatus.IN_FLIGHT:
                raise ValueError(f"claim {claim_id} is {claim.status.value}, not in_flight")
            if child.id in claim.child_task_ids:
                return claim  # already created on a prior attempt — idempotent no-op
            self.tasks.submit(child)
            return self.decomposition_claims.add_child(claim_id, child.id)

    def _fire_downstream_wakes(self, task_id: str) -> list[Wake]:
        """Enqueue ``deps_resolved`` / ``children_done`` wakes for a just-completed task."""
        fired: list[Wake] = []
        task = self.tasks.get(task_id)
        for dependent_id in self.dependencies.newly_unblocked_dependents(task_id):
            dependent = self.tasks.get(dependent_id)
            if dependent is not None and dependent.assignee_employee_id is not None:
                fired.append(
                    self.wakes.enqueue(
                        Wake(
                            id=_wake_id(),
                            employee_id=dependent.assignee_employee_id,
                            reason=WakeReason.DEPS_RESOLVED,
                            payload={"task_id": dependent_id},
                        )
                    )
                )
        if (
            task is not None
            and task.parent_id is not None
            and self.tasks.all_children_terminal(task.parent_id)
        ):
            parent = self.tasks.get(task.parent_id)
            if parent is not None and parent.assignee_employee_id is not None:
                fired.append(
                    self.wakes.enqueue(
                        Wake(
                            id=_wake_id(),
                            employee_id=parent.assignee_employee_id,
                            reason=WakeReason.CHILDREN_DONE,
                            payload={"task_id": task.parent_id},
                        )
                    )
                )
        return fired

    def close(self) -> None:
        self._conn.close()


__all__ = [
    "Ledger",
    "LedgerIntegrityError",
    "SchemaDriftError",
    "baseline",
    "ledger_table_names",
    "postgres_ddl",
]
