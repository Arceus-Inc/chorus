"""The spec 12 §5 conformance suite — one test set, every ``Ledger`` driver.

Each behavior here is a kernel-load-bearing contract (exact-once submit, checkout CAS,
terminal-only lock release, eligibility gating, wake coalescing, transaction batching). The suite is
parameterized over drivers: ``SqliteLedger`` and ``Ledger`` must pass identically — that is
what makes the driver swap proven, not hoped. Ids are minted (uuidv7 text): Postgres's native
``uuid`` columns enforce the id contract; SQLite's TEXT accepts the same values.

The Postgres side runs against a throwaway PostgreSQL 18 cluster (initdb + pg_ctl, no Docker),
skipped when PG18 isn't installed.
"""

from __future__ import annotations

import pytest

from chorus.ids import mint_id
from chorus.ledger import (
    Goal,
    Ledger,
    LedgerIntegrityError,
    OriginKind,
    Run,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)
from chorus.workforce import Employee, EmployeeStatus

pytestmark = pytest.mark.integration


# Overridable so CI (or a non-Homebrew machine) can point at its own PostgreSQL 18 install.
@pytest.fixture
def any_ledger(ledger: Ledger) -> Ledger:
    """The (one) driver under test — kept as a named seam from the two-driver era."""
    return ledger


def _employee(ledger: Ledger) -> Employee:
    return ledger.employees.create(Employee(id=mint_id(), name="alice", role="engineer"))


def _task(ledger: Ledger, **kwargs: object) -> Task:
    defaults: dict[str, object] = {"id": mint_id(), "intent": "build", "status": TaskStatus.TODO}
    defaults.update(kwargs)
    return ledger.tasks.submit(Task(**defaults))  # type: ignore[arg-type]


# --- employees / goals -----------------------------------------------------------------------


def test_employee_round_trip_and_status(any_ledger: Ledger) -> None:
    created = _employee(any_ledger)
    got = any_ledger.employees.get(created.id)
    assert got is not None and (got.name, got.role) == ("alice", "engineer")
    any_ledger.employees.set_status(created.id, EmployeeStatus.TERMINATED)
    updated = any_ledger.employees.get(created.id)
    assert updated is not None and updated.status is EmployeeStatus.TERMINATED
    assert any_ledger.employees.get(mint_id()) is None


def test_goal_round_trip(any_ledger: Ledger) -> None:
    goal_id = mint_id()
    any_ledger.goals.create(Goal(id=goal_id, title="ship login"))
    got = any_ledger.goals.get(goal_id)
    assert got is not None and got.title == "ship login"


# --- tasks: the load-bearing contract --------------------------------------------------------


def test_task_submit_and_get(any_ledger: Ledger) -> None:
    goal_id = mint_id()
    any_ledger.goals.create(Goal(id=goal_id, title="ship"))
    task = _task(any_ledger, intent="build login", goal_id=goal_id)
    got = any_ledger.tasks.get(task.id)
    assert got is not None
    assert (got.intent, got.status, got.goal_id) == ("build login", TaskStatus.TODO, goal_id)


def test_submit_is_exact_once_for_origin(any_ledger: Ledger) -> None:
    origin_id = mint_id()
    first = _task(
        any_ledger,
        origin_kind=OriginKind.STRANDED_RECOVERY,
        origin_id=origin_id,
    )
    assert first is not None
    # The DRIVER-NEUTRAL exception: SQLite and Postgres raise the same catchable name — the
    # kernel's exact-once handling (facade horizon-intake dedup, cron firing) depends on it.
    with pytest.raises(LedgerIntegrityError):
        _task(any_ledger, origin_kind=OriginKind.STRANDED_RECOVERY, origin_id=origin_id)


def test_exact_once_collision_leaves_the_ledger_usable(any_ledger: Ledger) -> None:
    """The kernel's normal pattern: try the insert, catch the violation, CONTINUE. On Postgres a
    naive driver would leave the transaction server-side aborted (every later statement fails
    InFailedSqlTransaction) — the savepoint-per-write emulation must absorb the failure."""
    origin_id = mint_id()
    _task(any_ledger, origin_kind=OriginKind.STRANDED_RECOVERY, origin_id=origin_id)
    with pytest.raises(LedgerIntegrityError):
        _task(any_ledger, origin_kind=OriginKind.STRANDED_RECOVERY, origin_id=origin_id)
    # Reads AND writes keep working on the same connection after the collision.
    survivor = _task(any_ledger, intent="after the collision")
    assert any_ledger.tasks.get(survivor.id) is not None
    assert len(any_ledger.tasks.list_eligible(limit=10)) >= 1
    # And the same holds INSIDE a facade transaction batch (catch-and-continue mid-batch).
    caught_inside = _task(any_ledger, intent="batch sibling")
    with any_ledger.transaction():
        with pytest.raises(LedgerIntegrityError):
            _task(any_ledger, origin_kind=OriginKind.STRANDED_RECOVERY, origin_id=origin_id)
        any_ledger.tasks.set_status(caught_inside.id, TaskStatus.DONE)  # continues, then commits
    refreshed = any_ledger.tasks.get(caught_inside.id)
    assert refreshed is not None and refreshed.status is TaskStatus.DONE


def test_checkout_conflict_is_409(any_ledger: Ledger) -> None:
    employee = _employee(any_ledger)
    task = _task(any_ledger)
    first_run, second_run = mint_id(), mint_id()
    assert any_ledger.tasks.checkout(task.id, employee_id=employee.id, run_id=first_run) is True
    assert any_ledger.tasks.checkout(task.id, employee_id=employee.id, run_id=second_run) is False
    got = any_ledger.tasks.get(task.id)
    assert got is not None
    assert got.status is TaskStatus.IN_PROGRESS
    assert got.checkout_run_id == first_run  # the loser never clobbers the winner


def test_release_locks_clears_for_the_owner(any_ledger: Ledger) -> None:
    employee = _employee(any_ledger)
    task = _task(any_ledger)
    run_id = mint_id()
    any_ledger.tasks.checkout(task.id, employee_id=employee.id, run_id=run_id)
    any_ledger.tasks.release_locks(task.id, run_id=run_id)
    got = any_ledger.tasks.get(task.id)
    assert got is not None and got.checkout_run_id is None and got.execution_run_id is None


def test_set_status_stamps_timestamps(any_ledger: Ledger) -> None:
    task = _task(any_ledger)
    any_ledger.tasks.set_status(task.id, TaskStatus.IN_PROGRESS)
    started = any_ledger.tasks.get(task.id)
    assert started is not None and started.started_at is not None
    any_ledger.tasks.set_status(task.id, TaskStatus.DONE)
    done = any_ledger.tasks.get(task.id)
    assert done is not None and done.completed_at is not None


def test_list_eligible_gates_on_dependencies(any_ledger: Ledger) -> None:
    _employee(any_ledger)
    blocker = _task(any_ledger, intent="first")
    dependent = _task(any_ledger, intent="second")
    any_ledger.dependencies.add(dependent.id, depends_on_id=blocker.id)
    eligible = {t.id for t in any_ledger.tasks.list_eligible(limit=10)}
    assert blocker.id in eligible
    assert dependent.id not in eligible  # withheld until the blocker lands
    any_ledger.tasks.set_status(blocker.id, TaskStatus.DONE)
    assert dependent.id in {t.id for t in any_ledger.tasks.list_eligible(limit=10)}


# --- wakes: coalescing + claim ----------------------------------------------------------------


def test_wake_coalesces_on_key_and_claims_once(any_ledger: Ledger) -> None:
    employee = _employee(any_ledger)
    task = _task(any_ledger)
    payload = {"task_id": task.id}
    first = any_ledger.wakes.enqueue(
        Wake(
            id=mint_id(), employee_id=employee.id, reason=WakeReason.DEPS_RESOLVED, payload=payload
        )
    )
    second = any_ledger.wakes.enqueue(
        Wake(
            id=mint_id(), employee_id=employee.id, reason=WakeReason.DEPS_RESOLVED, payload=payload
        )
    )
    assert second.id == first.id  # coalesced onto the queued row
    assert second.coalesced_count == 1
    claimed = any_ledger.wakes.claim(limit=10)
    assert [w.id for w in claimed] == [first.id]
    assert any_ledger.wakes.claim(limit=10) == []  # claim is exact-once


# --- runs --------------------------------------------------------------------------------------


def test_run_round_trip(any_ledger: Ledger) -> None:
    employee = _employee(any_ledger)
    task = _task(any_ledger)
    run_id = mint_id()
    any_ledger.runs.create(Run(id=run_id, employee_id=employee.id, task_id=task.id))
    got = any_ledger.runs.get(run_id)
    assert got is not None and got.task_id == task.id
    assert [r.id for r in any_ledger.runs.for_task(task.id)] == [run_id]


# --- the reviewer-flagged type-inference hot spots ----------------------------------------------


def test_dod_verdict_records_with_coalesce(any_ledger: Ledger) -> None:
    """`verified_by_run_id = COALESCE(?, verified_by_run_id)` — a NULL-able param feeding a uuid
    column via server-side inference (the flagged risk shape)."""
    from chorus.ledger import DodStatus
    from chorus.outcomes import Verifier

    employee = _employee(any_ledger)
    task = _task(any_ledger)
    dod = any_ledger.dod.create(task.id, Verifier.command("pytest -q", artifact_class="pr"))
    run_id = mint_id()
    any_ledger.runs.create(Run(id=run_id, employee_id=employee.id, task_id=task.id))
    any_ledger.dod.record_verdict(
        dod.id, DodStatus.PASSED, verdict={"passed": True, "notes": "solid"}, run_id=run_id
    )
    got = any_ledger.dod.get_for_task(task.id)
    assert got is not None
    assert got.status is DodStatus.PASSED
    assert got.verified_by_run_id == run_id
    assert got.verdict == {"notes": "solid", "passed": True}
    # And the NULL branch of the COALESCE: verdict-only update keeps the run id.
    any_ledger.dod.record_verdict(dod.id, DodStatus.FAILED, verdict={"passed": False})
    kept = any_ledger.dod.get_for_task(task.id)
    assert kept is not None and kept.verified_by_run_id == run_id


def test_run_finish_coalesces_outcome_and_usage(any_ledger: Ledger) -> None:
    from chorus.ledger import RunStatus

    employee = _employee(any_ledger)
    task = _task(any_ledger)
    run_id = mint_id()
    any_ledger.runs.create(Run(id=run_id, employee_id=employee.id, task_id=task.id))
    any_ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome={"ok": True}, usage={"tokens": 12})
    got = any_ledger.runs.get(run_id)
    assert got is not None
    assert got.status is RunStatus.SUCCEEDED
    assert (got.outcome, got.usage) == ({"ok": True}, {"tokens": 12})
    assert got.finished_at is not None


def test_timestamptz_comparisons_monitor_due_and_expired_lease(any_ledger: Ledger) -> None:
    """`col <= ?` with ISO-text params against timestamptz columns, and the datetime round-trip."""
    from datetime import UTC, datetime, timedelta

    from chorus.ledger import Monitor, Run, RunStatus

    employee = _employee(any_ledger)
    task = _task(any_ledger)
    now = datetime.now(UTC)
    any_ledger.monitors.arm(
        Monitor(
            id=mint_id(),
            task_id=task.id,
            employee_id=employee.id,
            next_check_at=now - timedelta(minutes=1),
        )
    )
    due = any_ledger.monitors.due(now=now)
    assert [monitor.task_id for monitor in due] == [task.id]
    assert due[0].next_check_at is not None  # round-tripped back to a datetime

    run_id = mint_id()
    any_ledger.runs.create(
        Run(
            id=run_id,
            employee_id=employee.id,
            task_id=task.id,
            status=RunStatus.RUNNING,
            lease_expires_at=now - timedelta(seconds=5),
        )
    )
    expired = any_ledger.runs.running_with_expired_lease(now)
    assert [run.id for run in expired] == [run_id]


def test_routine_trigger_claim_fire_cas_round_trips_timestamps(any_ledger: Ledger) -> None:
    """The double-fire guard: `UPDATE … WHERE next_run_at = ?` — timestamptz EQUALITY against a
    round-tripped datetime (write ISO → read text → parse → bind again). The strictest inference
    test in the repo set."""
    from datetime import UTC, datetime, timedelta

    from chorus.ledger import Routine, RoutineTrigger, TriggerKind

    employee = _employee(any_ledger)
    routine = any_ledger.routines.create(
        Routine(id=mint_id(), employee_id=employee.id, intent_template="tick")
    )
    first_edge = datetime.now(UTC).replace(microsecond=123456)
    trigger = any_ledger.routine_triggers.create(
        RoutineTrigger(
            id=mint_id(),
            routine_id=routine.id,
            kind=TriggerKind.CRON,
            cron_expression="* * * * *",
            next_run_at=first_edge,
        )
    )
    reread = any_ledger.routine_triggers.get(trigger.id)
    assert reread is not None and reread.next_run_at is not None
    next_edge = first_edge + timedelta(minutes=1)
    assert (
        any_ledger.routine_triggers.claim_fire(
            trigger.id, expected_next_run_at=reread.next_run_at, new_next_run_at=next_edge
        )
        is True
    )
    # The edge advanced — the same expected value must now lose (the whole point of the CAS).
    assert (
        any_ledger.routine_triggers.claim_fire(
            trigger.id, expected_next_run_at=reread.next_run_at, new_next_run_at=next_edge
        )
        is False
    )


def test_wake_claim_applies_the_dispatch_order(any_ledger: Ledger) -> None:
    """The kernel's dispatch ranking (resume-first, then priority band, then FIFO) — the most
    dialect-sensitive query in the repo set (correlated subquery + CASE over a join)."""
    from chorus.ledger import TaskPriority

    employee = _employee(any_ledger)
    low = _task(any_ledger, intent="low", priority=TaskPriority.LOW)
    critical = _task(any_ledger, intent="critical", priority=TaskPriority.CRITICAL)
    resumed = _task(any_ledger, intent="resumed", status=TaskStatus.IN_PROGRESS)
    for task in (low, critical, resumed):
        any_ledger.wakes.enqueue(
            Wake(
                id=mint_id(),
                employee_id=employee.id,
                reason=WakeReason.DEPS_RESOLVED,
                payload={"task_id": task.id},
            )
        )
    claimed = any_ledger.wakes.claim(limit=10)
    claimed_task_ids = [wake.payload.get("task_id") for wake in claimed]
    # in_progress resume outranks everything; then the priority band (critical before low).
    assert claimed_task_ids == [resumed.id, critical.id, low.id]


def test_cost_event_aggregation_sums_bigints(any_ledger: Ledger) -> None:
    from chorus.ledger import CostEvent

    employee = _employee(any_ledger)
    for cents in (150, 4_000_000_000):  # the second would wrap a 32-bit int
        any_ledger.cost_events.record(
            CostEvent(
                id=mint_id(),
                employee_id=employee.id,
                provider="azure",
                model="gpt",
                cost_cents=cents,
            )
        )
    assert any_ledger.cost_events.spent_cents(employee.id) == 4_000_000_150


def test_create_child_is_idempotent_on_retry(any_ledger: Ledger) -> None:
    from chorus.ledger import Artifact, ArtifactRevision, ArtifactType, DecompositionClaim

    parent = _task(any_ledger, intent="parent")
    plan = any_ledger.artifacts.create(
        Artifact(id=mint_id(), task_id=parent.id, type=ArtifactType.ARTIFACT)
    )
    revision = any_ledger.artifact_revisions.record(
        ArtifactRevision(id=mint_id(), artifact_id=plan.id)
    )
    claim = any_ledger.decomposition_claims.open(
        DecompositionClaim(
            id=mint_id(),
            source_task_id=parent.id,
            accepted_plan_revision_id=revision.id,
            requested_children=[{"intent": "child"}],
        )
    )
    child = Task(id=mint_id(), intent="child", status=TaskStatus.TODO, parent_id=parent.id)
    first = any_ledger.create_child(claim.id, child)
    again = any_ledger.create_child(claim.id, child)  # a resumed fan-out — no duplicate insert
    assert list(first.child_task_ids) == list(again.child_task_ids) == [child.id]


def test_approval_gate_is_exact_once_per_subject(any_ledger: Ledger) -> None:
    from chorus.ledger import Approval, ApprovalAction, ApprovalStatus, ApprovalSubjectKind

    task = _task(any_ledger)
    opened = any_ledger.approvals.request(
        Approval(
            id=mint_id(),
            subject_kind=ApprovalSubjectKind.TASK,
            subject_id=task.id,
            reason="hard stop",
            action=ApprovalAction.BUDGET_OVERRIDE,
        )
    )
    with pytest.raises(LedgerIntegrityError):  # a second PENDING gate for the same subject
        any_ledger.approvals.request(
            Approval(
                id=mint_id(),
                subject_kind=ApprovalSubjectKind.TASK,
                subject_id=task.id,
                reason="again",
                action=ApprovalAction.BUDGET_OVERRIDE,
            )
        )
    any_ledger.approvals.approve(opened.id, decided_by_user_id="operator")
    decided = any_ledger.approvals.get(opened.id)
    assert decided is not None and decided.status is ApprovalStatus.APPROVED


def test_message_round_trip(any_ledger: Ledger) -> None:
    from chorus.ledger import Message

    sender, receiver = _employee(any_ledger), _employee(any_ledger)
    sent = any_ledger.messages.send(
        Message(
            id=mint_id(),
            to_employee_id=receiver.id,
            body="ship it",
            from_employee_id=sender.id,
        )
    )
    got = any_ledger.messages.get(sent.id)
    assert got is not None and got.body == "ship it"


def test_workforce_plan_preserves_draft_order(any_ledger: Ledger) -> None:
    """Plan employees round-trip in DRAFT order — the explicit position column, on both engines."""
    from chorus.ledger import (
        PlannedEmployee,
        WorkforcePlan,
        WorkforcePlanDraft,
        WorkforcePlanStatus,
    )

    proposer = _employee(any_ledger)
    goal_id = mint_id()
    any_ledger.goals.create(Goal(id=goal_id, title="scale"))
    draft = WorkforcePlanDraft(
        rationale="scale the pod",
        confidence=0.9,
        source_goal_ids=(goal_id,),
        management_grants=(),
        employees=tuple(
            PlannedEmployee(ref=ref, name=ref.title(), profession="engineer", reports_to_ref="ceo")
            for ref in ("zulu", "alpha", "mike")  # deliberately not alphabetical
        ),
    )
    plan = any_ledger.workforce_plans.create(
        WorkforcePlan(
            id=mint_id(),
            revision=1,
            status=WorkforcePlanStatus.PROPOSED,
            proposed_by_employee_id=proposer.id,
            draft=draft,
        )
    )
    reread = any_ledger.workforce_plans.get(plan.id, revision=1)
    assert reread is not None
    assert [employee.ref for employee in reread.draft.employees] == ["zulu", "alpha", "mike"]


def test_activity_stream_preserves_append_order(any_ledger: Ledger) -> None:
    """The audit stream reads back oldest-first — append stamps occurred_at; ties break on the
    time-ordered id (the portable replacement for SQLite's rowid)."""
    from chorus.ledger import Activity, ActivityVerb

    task = _task(any_ledger)
    for verb in (ActivityVerb.LEAD_ACCEPTED, ActivityVerb.PARENT_VERIFIED):
        any_ledger.activity.append(
            Activity(id=mint_id(), verb=verb, subject_kind="task", subject_id=task.id)
        )
    history = any_ledger.activity.by_subject("task", task.id)
    assert [activity.verb for activity in history] == [
        ActivityVerb.LEAD_ACCEPTED,
        ActivityVerb.PARENT_VERIFIED,
    ]


# --- cross-aggregate: the facade's atomic operations -------------------------------------------


def test_transaction_batches_and_rolls_back(any_ledger: Ledger) -> None:
    employee = _employee(any_ledger)
    task_id = mint_id()
    with pytest.raises(RuntimeError):
        with any_ledger.transaction():
            _task(any_ledger, id=task_id)
            any_ledger.employees.set_status(employee.id, EmployeeStatus.TERMINATED)
            raise RuntimeError("boom")
    assert any_ledger.tasks.get(task_id) is None  # neither write survived
    still = any_ledger.employees.get(employee.id)
    assert still is not None and still.status is not EmployeeStatus.TERMINATED


def test_finalize_beat_fires_downstream_wakes(any_ledger: Ledger) -> None:
    from chorus.ledger import DodStatus

    employee = _employee(any_ledger)
    blocker = _task(any_ledger, intent="first")
    dependent = _task(any_ledger, intent="second", assignee_employee_id=employee.id)
    any_ledger.dependencies.add(dependent.id, depends_on_id=blocker.id)
    fired = any_ledger.finalize_beat(task_id=blocker.id, run_id=None, dod_status=DodStatus.PASSED)
    done = any_ledger.tasks.get(blocker.id)
    assert done is not None and done.status is TaskStatus.DONE
    assert [w.reason for w in fired] == [WakeReason.DEPS_RESOLVED]
    assert fired[0].employee_id == employee.id


# --- Postgres-native storage (the whole point) --------------------------------------------------


def test_postgres_columns_are_native_types(pg_database: str) -> None:
    """uuid ids, timestamptz times, jsonb blobs, boolean flags — native, never intersection text."""
    if pg_database is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    ledger = Ledger.open(pg_database)
    try:
        import psycopg

        expected = {
            ("task", "id"): "uuid",
            ("task", "parent_id"): "uuid",
            ("task", "checkout_run_id"): "uuid",
            ("task", "created_at"): "timestamp with time zone",
            ("task", "origin_id"): "text",  # polymorphic by design — stays text
            ("task", "assignee_user_id"): "text",  # external principal ref — stays text
            ("run", "id"): "uuid",
            ("run", "lease_expires_at"): "timestamp with time zone",
            ("run", "outcome"): "jsonb",
            ("run", "system_principal_id"): "text",  # semantic id ('system-verifier')
            ("wake", "payload"): "jsonb",
            ("wake", "task_id"): "uuid",
            # Employee ids are semantic slugs ("ace") — text, company-scoped composite PK.
            ("employee", "id"): "text",
            ("employee", "budget_monthly_cents"): "bigint",
            ("management_profile", "can_lead"): "boolean",
            ("delegation_contract", "can_subdelegate"): "boolean",
            ("delegation_contract", "spend_limit_cents"): "bigint",
            ("workforce_plan", "confidence"): "double precision",
            ("system_principal", "id"): "text",
            ("decision_record", "task_id"): "uuid",
            ("claim", "decision_id"): "uuid",
            # Tenancy: every table carries the company discriminator (M5 shared-schema shape).
            ("task", "company_id"): "uuid",
            ("wake", "company_id"): "uuid",
            ("system_principal", "company_id"): "uuid",
        }
        with psycopg.connect(pg_database) as conn:
            rows = conn.execute(
                "SELECT table_name, column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'public'"
            ).fetchall()
        found = {(r[0], r[1]): r[2] for r in rows}
        wrong = {
            key: (found.get(key), want) for key, want in expected.items() if found.get(key) != want
        }
        assert wrong == {}, f"(column): (actual, expected) -> {wrong}"
    finally:
        ledger.close()


# --- Postgres tenancy: company_id + FORCE RLS (M5 shared-schema shape) --------------------------


def _app_role_conninfo(pg_database: str, admin_grants: bool = True) -> str:
    """Create (once) a non-superuser NOBYPASSRLS role and grant it the ledger tables."""
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'chorus_app') "
            "THEN CREATE ROLE chorus_app LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        if admin_grants:
            admin.execute("GRANT USAGE ON SCHEMA public TO chorus_app")
            admin.execute(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO chorus_app"
            )
    return pg_database.replace("user=postgres", "user=chorus_app")


def test_postgres_isolates_companies_with_force_rls(pg_database: str) -> None:
    """Two companies, one database: A's rows are invisible to B, writes auto-stamp the session's
    company, and a session with no company context fails closed. Proven under a NON-superuser
    role (FORCE RLS bites; superusers bypass row security entirely)."""
    if pg_database is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    bootstrap = Ledger.open(pg_database, company_id=mint_id())  # owner applies DDL
    bootstrap.close()
    app_conninfo = _app_role_conninfo(pg_database)

    company_a, company_b = mint_id(), mint_id()
    ledger_a = Ledger.open(app_conninfo, company_id=company_a)
    ledger_b = Ledger.open(app_conninfo, company_id=company_b)
    try:
        task = _task(ledger_a, intent="secret work")
        assert ledger_a.tasks.get(task.id) is not None  # A sees its own row
        assert ledger_b.tasks.get(task.id) is None  # B sees nothing of A's
        assert ledger_b.tasks.list_eligible(limit=10) == []
        # B's write lands in B — visible to B, invisible to A (auto-stamped company_id).
        b_task = _task(ledger_b, intent="b work")
        assert ledger_b.tasks.get(b_task.id) is not None
        assert ledger_a.tasks.get(b_task.id) is None
        # (Cross-company reuse of a NON-id key is covered by the horizon-fingerprint test below;
        # id-anchored uniques stay global on purpose — minted uuids never repeat across companies.)
    finally:
        ledger_a.close()
        ledger_b.close()

    # No company context at all -> inserts fail closed (NOT NULL company_id from a NULL GUC).
    naked = Ledger.open(app_conninfo)
    try:
        with pytest.raises(Exception):
            _task(naked)
        naked._conn.rollback()
        assert naked.tasks.list_eligible(limit=10) == []  # and reads see zero rows
    finally:
        naked.close()


def test_postgres_employee_slugs_are_company_scoped(pg_database: str) -> None:
    """Two companies may both employ "ace" (composite PK); within one company the slug is unique.
    This is the regression test for slug identity in the shared schema (spec 06 §3 slugs)."""
    if pg_database is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    Ledger.open(pg_database, company_id=mint_id()).close()
    app_conninfo = _app_role_conninfo(pg_database)
    ledger_a = Ledger.open(app_conninfo, company_id=mint_id())
    ledger_b = Ledger.open(app_conninfo, company_id=mint_id())
    try:
        ledger_a.employees.create(Employee(id="ace", name="Ace", role="engineer"))
        ledger_b.employees.create(Employee(id="ace", name="Ace", role="engineer"))  # no collision
        got_b = ledger_b.employees.get("ace")
        assert got_b is not None and got_b.name == "Ace"
        with pytest.raises(Exception):
            ledger_a.employees.create(Employee(id="ace", name="Ace 2", role="pm"))
    finally:
        ledger_a.close()
        ledger_b.close()


def test_postgres_horizon_fingerprint_is_company_scoped(pg_database: str) -> None:
    """The one non-id-anchored exact-once index: two companies may carry the same intake
    fingerprint; within one company it stays exact-once."""
    if pg_database is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    Ledger.open(pg_database, company_id=mint_id()).close()
    app_conninfo = _app_role_conninfo(pg_database)
    ledger_a = Ledger.open(app_conninfo, company_id=mint_id())
    ledger_b = Ledger.open(app_conninfo, company_id=mint_id())
    try:
        fingerprint = "sha256:same-directive"
        _task(ledger_a, origin_kind=OriginKind.HORIZON_INTAKE, origin_fingerprint=fingerprint)
        _task(ledger_b, origin_kind=OriginKind.HORIZON_INTAKE, origin_fingerprint=fingerprint)
        with pytest.raises(Exception):
            _task(ledger_a, origin_kind=OriginKind.HORIZON_INTAKE, origin_fingerprint=fingerprint)
    finally:
        ledger_a.close()
        ledger_b.close()


def test_postgres_two_connections_share_one_company_concurrently(pg_database: str) -> None:
    """The M5/M4 unblock: the api process and the conductor process hold SEPARATE connections to
    the SAME company's ledger and interleave reads and writes consistently — the thing a
    SQLite-file-per-company could never do across processes."""
    if pg_database is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_database, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    Ledger.open(pg_database, company_id=mint_id()).close()
    app_conninfo = _app_role_conninfo(pg_database)
    company_id = mint_id()
    conductor_side = Ledger.open(app_conninfo, company_id=company_id)
    api_side = Ledger.open(app_conninfo, company_id=company_id)
    try:
        employee = _employee(conductor_side)  # the conductor hires...
        task = _task(api_side, intent="from the api")  # ...the api submits...
        run_id = mint_id()
        assert (
            conductor_side.tasks.checkout(task.id, employee_id=employee.id, run_id=run_id) is True
        )
        seen = api_side.tasks.get(task.id)  # ...and each sees the other's committed writes.
        assert seen is not None and seen.status is TaskStatus.IN_PROGRESS
        assert seen.checkout_run_id == run_id
        # The CAS still arbitrates across connections: the api's competing checkout loses cleanly.
        assert api_side.tasks.checkout(task.id, employee_id=employee.id, run_id=mint_id()) is False
    finally:
        conductor_side.close()
        api_side.close()


def test_management_profile_upsert_round_trips(any_ledger: Ledger) -> None:
    """The upsert's ON CONFLICT target must match the (company_id, employee_id) PK on BOTH
    engines — the exact class of bug the wake coalesce fix covered (found live on Postgres)."""
    from chorus.ledger import ManagementProfile

    lead = _employee(any_ledger)
    first = ManagementProfile(
        employee_id=lead.id,
        active=True,
        can_lead=True,
        can_subdelegate=False,
        max_delegation_depth=1,
        max_team_size=3,
        allowed_professions=("engineer",),
        version=1,
        granted_by_user_id="operator",
    )
    any_ledger.management_profiles.upsert(first)
    second = ManagementProfile(
        employee_id=lead.id,
        active=True,
        can_lead=True,
        can_subdelegate=True,
        max_delegation_depth=2,
        max_team_size=5,
        allowed_professions=("engineer", "designer"),
        version=2,
        granted_by_user_id="operator",
    )
    any_ledger.management_profiles.upsert(second)  # the conflict path — updates in place
    got = any_ledger.management_profiles.get(lead.id)
    assert got is not None
    assert (got.version, got.max_team_size, got.can_subdelegate) == (2, 5, True)
    assert [
        profile.employee_id for profile in any_ledger.management_profiles.active_profiles()
    ] == [lead.id]


def test_every_global_unique_index_is_a_deliberate_decision() -> None:
    """Guardrail for the company-scoping allowlist: a NEW unique index that is not company-scoped
    must be added to this frozen set consciously — a silent global unique is exactly how the
    management_profile ON CONFLICT bug slipped past the SQLite-only tests. Everything here is
    anchored on a chorus-minted uuid, so global uniqueness is safe across companies."""
    import re

    from chorus.ledger import postgres_ddl

    pattern = re.compile(r"CREATE UNIQUE INDEX (\w+)\s+ON\s+\w+\s*\(([^)]*)\)", re.S)
    global_uniques = {
        match.group(1)
        for statement in postgres_ddl()
        for match in [pattern.search(statement)]
        if match is not None and not match.group(2).strip().startswith("company_id")
    }
    assert global_uniques == {
        "approval_subject_pending_uq",  # subject_id = a minted task/artifact uuid
        "artifact_revision_seq_uq",  # artifact_id
        "budget_incident_window_uq",  # policy_id
        "decomp_source_revision_uq",  # source_task_id + accepted_plan_revision_id
        "dod_task_uq",  # task_id
        "monitor_armed_task_uq",  # task_id
        "recovery_active_fingerprint_uq",  # source_task_id
        "recovery_active_source_uq",  # source_task_id
        "routine_revision_no_uq",  # routine_id
        "task_active_productivity_review_uq",  # origin_id = a minted id
        "task_active_stale_run_eval_uq",  # origin_id
        "task_active_stranded_recovery_uq",  # origin_id
        "task_dependency_uq",  # task_id + depends_on_id
        "task_open_routine_uq",  # origin_id = the routine uuid
    }
