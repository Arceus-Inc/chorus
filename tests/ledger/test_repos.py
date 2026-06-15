"""Repo-layer + facade tests (spec 01, Arceus-style per-aggregate repos).

The ``SqliteLedger`` facade opens a connection, applies migrations, and exposes
one repo per aggregate (``employees``/``goals``/``tasks``/``runs``/``dod``/
``artifacts``). Repos speak intersection SQL, so the same code runs on Postgres
later (spec 12). The load-bearing path — exact-once submit, checkout CAS,
eligibility — is exercised here at the repo API.
"""

from __future__ import annotations

import sqlite3

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactType,
    DodStatus,
    Goal,
    OriginKind,
    Run,
    RunStatus,
    SqliteLedger,
    Task,
    TaskStatus,
)
from chorus.outcomes import Verifier
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def test_open_applies_schema_and_reports_version(ledger: SqliteLedger) -> None:
    from chorus.ledger.migrations import MIGRATIONS

    assert ledger.schema_version() == MIGRATIONS[-1].id


def test_employee_create_and_get(ledger: SqliteLedger) -> None:
    created = ledger.employees.create(Employee(id="e1", name="alice", role="engineer"))
    assert created.id == "e1"
    got = ledger.employees.get("e1")
    assert got is not None
    assert got.name == "alice"
    assert got.role == "engineer"
    assert ledger.employees.get("missing") is None


def test_goal_create_and_get(ledger: SqliteLedger) -> None:
    ledger.goals.create(Goal(id="g1", title="ship login"))
    got = ledger.goals.get("g1")
    assert got is not None
    assert got.title == "ship login"


def test_task_submit_and_get(ledger: SqliteLedger) -> None:
    ledger.goals.create(Goal(id="g1", title="ship"))
    ledger.tasks.submit(Task(id="t1", intent="build login", status=TaskStatus.TODO, goal_id="g1"))
    got = ledger.tasks.get("t1")
    assert got is not None
    assert got.intent == "build login"
    assert got.status is TaskStatus.TODO
    assert got.goal_id == "g1"


def test_checkout_cas_grants_single_owner(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO))
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="r1") is True
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="r2") is False
    got = ledger.tasks.get("t1")
    assert got is not None
    assert got.status is TaskStatus.IN_PROGRESS
    assert got.checkout_run_id == "r1"
    assert got.assignee_employee_id == "e1"


def test_release_locks_clears_when_owner(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO))
    ledger.tasks.checkout("t1", employee_id="e1", run_id="r1")
    ledger.tasks.release_locks("t1", run_id="r1")
    got = ledger.tasks.get("t1")
    assert got is not None
    assert got.checkout_run_id is None
    assert got.execution_run_id is None


def test_set_status(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO))
    ledger.tasks.set_status("t1", TaskStatus.DONE)
    got = ledger.tasks.get("t1")
    assert got is not None
    assert got.status is TaskStatus.DONE


def test_list_eligible_returns_only_unclaimed_todo(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id="t2", intent="y", status=TaskStatus.BACKLOG))  # not actionable
    ledger.tasks.submit(Task(id="t3", intent="z", status=TaskStatus.TODO))
    ledger.tasks.checkout("t3", employee_id="e1", run_id="r1")  # claimed → excluded
    eligible = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert eligible == ["t1"]


def test_exact_once_self_spawned_submit_is_rejected(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(
        Task(
            id="rec1",
            intent="recover",
            status=TaskStatus.TODO,
            origin_kind=OriginKind.STRANDED_RECOVERY,
            origin_id="src1",
        )
    )
    with pytest.raises(sqlite3.IntegrityError):
        ledger.tasks.submit(
            Task(
                id="rec2",
                intent="recover",
                status=TaskStatus.TODO,
                origin_kind=OriginKind.STRANDED_RECOVERY,
                origin_id="src1",
            )
        )


def test_run_create_and_finish(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.runs.create(Run(id="r1", employee_id="e1", task_id="t1"))
    assert ledger.runs.get("r1").status is RunStatus.QUEUED  # type: ignore[union-attr]
    ledger.runs.finish("r1", RunStatus.SUCCEEDED, liveness_state="completed", outcome={"passed": True})
    got = ledger.runs.get("r1")
    assert got is not None
    assert got.status is RunStatus.SUCCEEDED
    assert got.liveness_state == "completed"
    assert got.outcome == {"passed": True}


def test_dod_create_get_and_record_verdict(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x"))
    created = ledger.dod.create("t1", Verifier.command("pytest -q"))
    got = ledger.dod.get_for_task("t1")
    assert got is not None
    assert got.kind == "command"
    assert got.status is DodStatus.PENDING
    assert got.spec["command"] == "pytest -q"
    ledger.dod.record_verdict(created.id, DodStatus.PASSED, verdict={"score": 1.0})
    after = ledger.dod.get_for_task("t1")
    assert after is not None
    assert after.status is DodStatus.PASSED
    assert after.verdict == {"score": 1.0}


def test_dod_is_one_per_task(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.dod.create("t1", Verifier.command("pytest"))
    with pytest.raises(sqlite3.IntegrityError):
        ledger.dod.create("t1", Verifier.command("ruff"))


def test_artifact_create_and_list(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.artifacts.create(
        Artifact(id="a1", task_id="t1", type=ArtifactType.PR, url="http://pr/1", is_primary=True)
    )
    arts = ledger.artifacts.list_for_task("t1")
    assert len(arts) == 1
    assert arts[0].type is ArtifactType.PR
    assert arts[0].is_primary is True


def test_finish_preserves_liveness_when_omitted(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x"))
    ledger.runs.create(Run(id="r1", employee_id="e1", task_id="t1"))
    ledger.runs.finish("r1", RunStatus.RUNNING, liveness_state="advanced")
    ledger.runs.finish("r1", RunStatus.SUCCEEDED)  # omit liveness_state
    got = ledger.runs.get("r1")
    assert got is not None
    assert got.status is RunStatus.SUCCEEDED
    assert got.liveness_state == "advanced"  # preserved, not erased


def test_checkout_of_user_owned_task_returns_false(ledger: SqliteLedger) -> None:
    ledger.employees.create(Employee(id="e1", name="a", role="engineer"))
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO, assignee_user_id="u1"))
    # CAS must fail cleanly (a human owns it) — not raise IntegrityError on the XOR CHECK.
    assert ledger.tasks.checkout("t1", employee_id="e1", run_id="r1") is False
    got = ledger.tasks.get("t1")
    assert got is not None
    assert got.assignee_user_id == "u1"
    assert got.checkout_run_id is None


def test_list_eligible_excludes_human_owned(ledger: SqliteLedger) -> None:
    ledger.tasks.submit(Task(id="t1", intent="x", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id="t2", intent="y", status=TaskStatus.TODO, assignee_user_id="u1"))
    # human-owned t2 is excluded — checkout would always reject it (eligibility ⇔ claimability)
    assert [t.id for t in ledger.tasks.list_eligible(limit=10)] == ["t1"]
