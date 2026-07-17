"""The spec 12 §5 conformance suite — one test set, every ``Ledger`` driver.

Each behavior here is a kernel-load-bearing contract (exact-once submit, checkout CAS,
terminal-only lock release, eligibility gating, wake coalescing, transaction batching). The suite is
parameterized over drivers: ``SqliteLedger`` and ``PostgresLedger`` must pass identically — that is
what makes the driver swap proven, not hoped. Ids are minted (uuidv7 text): Postgres's native
``uuid`` columns enforce the id contract; SQLite's TEXT accepts the same values.

The Postgres side runs against a throwaway PostgreSQL 18 cluster (initdb + pg_ctl, no Docker),
skipped when PG18 isn't installed.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from chorus.ids import mint_id
from chorus.ledger import (
    Goal,
    Ledger,
    OriginKind,
    Run,
    SqliteLedger,
    Task,
    TaskStatus,
    Wake,
    WakeReason,
)
from chorus.ledger.postgres import PostgresLedger
from chorus.workforce import Employee, EmployeeStatus

pytestmark = pytest.mark.integration

_PG_BIN = Path("/opt/homebrew/opt/postgresql@18/bin")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def pg_conninfo(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str | None]:
    """A session-scoped throwaway PG18 cluster, or ``None`` when PG18 isn't installed."""
    if not _PG_BIN.exists():
        yield None
        return
    data = tmp_path_factory.mktemp("chorus_pgdata")
    env = {**os.environ, "LC_ALL": "C"}
    subprocess.run(
        [
            str(_PG_BIN / "initdb"),
            "-D",
            str(data),
            "-U",
            "postgres",
            "--auth=trust",
            "--encoding=UTF8",
            "--locale=C",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    port = _free_port()
    subprocess.run(
        [
            str(_PG_BIN / "pg_ctl"),
            "-D",
            str(data),
            "-o",
            f"-p {port} -c listen_addresses=127.0.0.1",
            "-l",
            str(data / "log"),
            "-w",
            "start",
        ],
        check=True,
        capture_output=True,
        env=env,
    )
    try:
        yield f"host=127.0.0.1 port={port} user=postgres dbname=postgres"
    finally:
        subprocess.run(
            [str(_PG_BIN / "pg_ctl"), "-D", str(data), "-w", "stop"],
            capture_output=True,
            env=env,
        )
        shutil.rmtree(data, ignore_errors=True)


@pytest.fixture(params=["sqlite", "postgres"])
def any_ledger(request: pytest.FixtureRequest, pg_conninfo: str | None) -> Iterator[Ledger]:
    """The driver under test. Every test below runs once per driver — identical assertions."""
    if request.param == "sqlite":
        ledger: Ledger = SqliteLedger.open(":memory:")
    else:
        if pg_conninfo is None:
            pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
        import psycopg

        with psycopg.connect(pg_conninfo, autocommit=True) as admin:
            admin.execute("DROP SCHEMA public CASCADE")
            admin.execute("CREATE SCHEMA public")
        ledger = PostgresLedger.open(pg_conninfo)
    try:
        yield ledger
    finally:
        ledger.close()


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
    with pytest.raises(Exception):
        _task(any_ledger, origin_kind=OriginKind.STRANDED_RECOVERY, origin_id=origin_id)


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


def test_postgres_columns_are_native_types(pg_conninfo: str | None) -> None:
    """uuid ids, timestamptz times, jsonb blobs, boolean flags — native, never intersection text."""
    if pg_conninfo is None:
        pytest.skip(f"PostgreSQL 18 not found at {_PG_BIN}")
    import psycopg

    with psycopg.connect(pg_conninfo, autocommit=True) as admin:
        admin.execute("DROP SCHEMA public CASCADE")
        admin.execute("CREATE SCHEMA public")
    ledger = PostgresLedger.open(pg_conninfo)
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
            ("employee", "id"): "uuid",
            ("employee", "budget_monthly_cents"): "bigint",
            ("management_profile", "can_lead"): "boolean",
            ("delegation_contract", "can_subdelegate"): "boolean",
            ("delegation_contract", "spend_limit_cents"): "bigint",
            ("workforce_plan", "confidence"): "double precision",
            ("system_principal", "id"): "text",
        }
        with psycopg.connect(pg_conninfo) as conn:
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
