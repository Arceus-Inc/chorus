"""Repo-layer + facade tests (spec 01, Arceus-style per-aggregate repos).

The ``Ledger`` facade opens a connection, applies migrations, and exposes
one repo per aggregate (``employees``/``goals``/``tasks``/``runs``/``dod``/
``artifacts``). Repos speak intersection SQL, so the same code runs on Postgres
later (spec 12). The load-bearing path — exact-once submit, checkout CAS,
eligibility — is exercised here at the repo API.
"""

from __future__ import annotations

import pytest

from chorus.ledger import (
    Artifact,
    ArtifactType,
    DodStatus,
    Goal,
    Ledger,
    LedgerIntegrityError,
    OriginKind,
    Run,
    RunStatus,
    Task,
    TaskStatus,
    load_migrations,
)
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee, EmployeeStatus

pytestmark = pytest.mark.integration


def test_open_applies_schema_and_reports_version(ledger: Ledger) -> None:

    assert ledger.schema_version() == load_migrations()[-1].id  # newest applied delta


def test_employee_create_and_get(ledger: Ledger) -> None:
    created = ledger.employees.create(Employee(id=uid("e1"), name="alice", role="engineer"))
    assert created.id == uid("e1")
    got = ledger.employees.get(uid("e1"))
    assert got is not None
    assert got.name == "alice"
    assert got.role == "engineer"
    assert ledger.employees.get(uid("missing")) is None


def test_employee_list_returns_every_row(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.employees.create(Employee(id=uid("e2"), name="b", role="engineer", reports_to=uid("e1")))
    assert {e.id for e in ledger.employees.list()} == {uid("e1"), uid("e2")}


def test_employee_list_is_empty_on_a_fresh_ledger(ledger: Ledger) -> None:
    assert ledger.employees.list() == []


def test_employee_set_status_transitions(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.employees.set_status(uid("e1"), EmployeeStatus.TERMINATED)
    got = ledger.employees.get(uid("e1"))
    assert got is not None
    assert got.status is EmployeeStatus.TERMINATED


def test_goal_create_and_get(ledger: Ledger) -> None:
    ledger.goals.create(Goal(id=uid("g1"), title="ship login"))
    got = ledger.goals.get(uid("g1"))
    assert got is not None
    assert got.title == "ship login"


def test_task_submit_and_get(ledger: Ledger) -> None:
    ledger.goals.create(Goal(id=uid("g1"), title="ship"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="build login", status=TaskStatus.TODO, goal_id=uid("g1"))
    )
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.intent == "build login"
    assert got.status is TaskStatus.TODO
    assert got.goal_id == uid("g1")


def test_checkout_cas_grants_single_owner(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.TODO))
    assert ledger.tasks.checkout(uid("t1"), employee_id=uid("e1"), run_id=uid("r1")) is True
    assert ledger.tasks.checkout(uid("t1"), employee_id=uid("e1"), run_id=uid("r2")) is False
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.status is TaskStatus.IN_PROGRESS
    assert got.checkout_run_id == uid("r1")
    assert got.assignee_employee_id == uid("e1")


def test_release_locks_clears_when_owner(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.TODO))
    ledger.tasks.checkout(uid("t1"), employee_id=uid("e1"), run_id=uid("r1"))
    ledger.tasks.release_locks(uid("t1"), run_id=uid("r1"))
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.checkout_run_id is None
    assert got.execution_run_id is None


def test_set_status(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.TODO))
    ledger.tasks.set_status(uid("t1"), TaskStatus.DONE)
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.status is TaskStatus.DONE


def test_list_eligible_returns_only_unclaimed_todo(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.TODO))
    ledger.tasks.submit(Task(id=uid("t2"), intent="y", status=TaskStatus.BACKLOG))  # not actionable
    ledger.tasks.submit(Task(id=uid("t3"), intent="z", status=TaskStatus.TODO))
    ledger.tasks.checkout(uid("t3"), employee_id=uid("e1"), run_id=uid("r1"))  # claimed → excluded
    eligible = [t.id for t in ledger.tasks.list_eligible(limit=10)]
    assert eligible == [uid("t1")]


def test_open_for_assignee_returns_none_without_a_workable_task(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.employees.create(Employee(id=uid("e2"), name="b", role="engineer"))
    # no tasks at all
    assert ledger.tasks.open_for_assignee(uid("e1")) is None
    # a task assigned to someone else, and one of ours that is terminal, are both ignored
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="x", status=TaskStatus.TODO, assignee_employee_id=uid("e2"))
    )
    ledger.tasks.submit(
        Task(id=uid("t2"), intent="y", status=TaskStatus.DONE, assignee_employee_id=uid("e1"))
    )
    ledger.tasks.submit(
        Task(id=uid("t3"), intent="z", status=TaskStatus.CANCELLED, assignee_employee_id=uid("e1"))
    )
    assert ledger.tasks.open_for_assignee(uid("e1")) is None


def test_open_for_assignee_returns_the_workable_task(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="x", status=TaskStatus.TODO, assignee_employee_id=uid("e1"))
    )
    got = ledger.tasks.open_for_assignee(uid("e1"))
    assert got is not None
    assert got.id == uid("t1")
    # blocked is not workable — a steer should not silently re-wake a blocked task
    ledger.tasks.set_status(uid("t1"), TaskStatus.BLOCKED)
    assert ledger.tasks.open_for_assignee(uid("e1")) is None


def test_open_for_assignee_prefers_the_most_recent(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="x", status=TaskStatus.TODO, assignee_employee_id=uid("e1"))
    )
    ledger.tasks.submit(
        Task(id=uid("t2"), intent="y", status=TaskStatus.TODO, assignee_employee_id=uid("e1"))
    )
    got = ledger.tasks.open_for_assignee(uid("e1"))
    assert got is not None
    assert got.id == uid("t2")


def test_exact_once_self_spawned_submit_is_rejected(ledger: Ledger) -> None:
    ledger.tasks.submit(
        Task(
            id=uid("rec1"),
            intent="recover",
            status=TaskStatus.TODO,
            origin_kind=OriginKind.STRANDED_RECOVERY,
            origin_id=uid("src1"),
        )
    )
    with pytest.raises(LedgerIntegrityError):
        ledger.tasks.submit(
            Task(
                id=uid("rec2"),
                intent="recover",
                status=TaskStatus.TODO,
                origin_kind=OriginKind.STRANDED_RECOVERY,
                origin_id=uid("src1"),
            )
        )


def test_run_create_and_finish(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(Run(id=uid("r1"), employee_id=uid("e1"), task_id=uid("t1")))
    assert ledger.runs.get(uid("r1")).status is RunStatus.QUEUED  # type: ignore[union-attr]
    ledger.runs.finish(
        uid("r1"), RunStatus.SUCCEEDED, liveness_state="completed", outcome={"passed": True}
    )
    got = ledger.runs.get(uid("r1"))
    assert got is not None
    assert got.status is RunStatus.SUCCEEDED
    assert got.liveness_state == "completed"
    assert got.outcome == {"passed": True}


def test_run_records_a_system_principal_separately_from_its_employee_host(
    ledger: Ledger,
) -> None:
    ledger.employees.create(Employee(id="author", name="Author", role="backend_engineer"))
    ledger.tasks.submit(Task(id=uid("code"), intent="ship it"))
    ledger.runs.create(
        Run(
            id=uid("verify"),
            employee_id="author",
            task_id=uid("code"),
            principal_kind="system",
            system_principal_id="system-verifier",
        )
    )

    run = ledger.runs.get(uid("verify"))
    assert run is not None
    assert run.employee_id == "author"
    assert run.principal_kind == "system"
    assert run.system_principal_id == "system-verifier"
    assert run.principal_id == "system-verifier"


def test_cancel_running_only_touches_running_and_returns_their_ids(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(
        Run(id=uid("live"), employee_id=uid("e1"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.runs.create(
        Run(id=uid("done"), employee_id=uid("e1"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.runs.finish(uid("done"), RunStatus.SUCCEEDED)  # terminal before the kill

    cancelled = ledger.runs.cancel_running(employee_id=uid("e1"))

    assert cancelled == [uid("live")]  # only the still-running row, reported exactly
    assert ledger.runs.get(uid("live")).status is RunStatus.CANCELLED  # type: ignore[union-attr]
    assert ledger.runs.get(uid("done")).status is RunStatus.SUCCEEDED  # type: ignore[union-attr]


def test_cancel_running_scopes_to_one_employee(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.employees.create(Employee(id=uid("e2"), name="b", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(
        Run(id=uid("r1"), employee_id=uid("e1"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )
    ledger.runs.create(
        Run(id=uid("r2"), employee_id=uid("e2"), task_id=uid("t1"), status=RunStatus.RUNNING)
    )

    assert ledger.runs.cancel_running(employee_id=uid("e1")) == [uid("r1")]
    assert ledger.runs.get(uid("r2")).status is RunStatus.RUNNING  # type: ignore[union-attr]


def test_verifier_for_task_round_trips_command(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.dod.create(uid("t1"), Verifier.command("pytest -q", artifact_class="pr", timeout_s=120))
    assert ledger.dod.verifier_for_task(uid("t1")) == Verifier.command(
        "pytest -q", artifact_class="pr", timeout_s=120
    )


def test_verifier_for_task_round_trips_agent_review(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.dod.create(
        uid("t1"), Verifier.agent_review(reviewer_role="reviewer", rubric="be strict")
    )
    assert ledger.dod.verifier_for_task(uid("t1")) == Verifier.agent_review(
        reviewer_role="reviewer", rubric="be strict"
    )


def test_verifier_for_task_round_trips_human_approval(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.dod.create(uid("t1"), Verifier.human_approval(approver="board"))
    assert ledger.dod.verifier_for_task(uid("t1")) == Verifier.human_approval(approver="board")


def test_verifier_for_task_none_without_a_dod(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    assert ledger.dod.verifier_for_task(uid("t1")) is None


def test_dod_create_get_and_record_verdict(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    created = ledger.dod.create(uid("t1"), Verifier.command("pytest -q"))
    got = ledger.dod.get_for_task(uid("t1"))
    assert got is not None
    assert got.kind == "command"
    assert got.status is DodStatus.PENDING
    assert got.spec["command"] == "pytest -q"
    ledger.dod.record_verdict(created.id, DodStatus.PASSED, verdict={"score": 1.0})
    after = ledger.dod.get_for_task(uid("t1"))
    assert after is not None
    assert after.status is DodStatus.PASSED
    assert after.verdict == {"score": 1.0}


def test_dod_is_one_per_task(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.dod.create(uid("t1"), Verifier.command("pytest"))
    with pytest.raises(LedgerIntegrityError):
        ledger.dod.create(uid("t1"), Verifier.command("ruff"))


def test_artifact_create_and_list(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.artifacts.create(
        Artifact(
            id=uid("a1"),
            task_id=uid("t1"),
            type=ArtifactType.PR,
            url="http://pr/1",
            is_primary=True,
        )
    )
    arts = ledger.artifacts.list_for_task(uid("t1"))
    assert len(arts) == 1
    assert arts[0].type is ArtifactType.PR
    assert arts[0].is_primary is True


def test_finish_preserves_liveness_when_omitted(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(Task(id=uid("t1"), intent="x"))
    ledger.runs.create(Run(id=uid("r1"), employee_id=uid("e1"), task_id=uid("t1")))
    ledger.runs.finish(uid("r1"), RunStatus.RUNNING, liveness_state="advanced")
    ledger.runs.finish(uid("r1"), RunStatus.SUCCEEDED)  # omit liveness_state
    got = ledger.runs.get(uid("r1"))
    assert got is not None
    assert got.status is RunStatus.SUCCEEDED
    assert got.liveness_state == "advanced"  # preserved, not erased


def test_checkout_of_user_owned_task_returns_false(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id=uid("e1"), name="a", role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("t1"), intent="x", status=TaskStatus.TODO, assignee_user_id=uid("u1"))
    )
    # CAS must fail cleanly (a human owns it) — not raise IntegrityError on the XOR CHECK.
    assert ledger.tasks.checkout(uid("t1"), employee_id=uid("e1"), run_id=uid("r1")) is False
    got = ledger.tasks.get(uid("t1"))
    assert got is not None
    assert got.assignee_user_id == uid("u1")
    assert got.checkout_run_id is None


def test_list_eligible_excludes_human_owned(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("t1"), intent="x", status=TaskStatus.TODO))
    ledger.tasks.submit(
        Task(id=uid("t2"), intent="y", status=TaskStatus.TODO, assignee_user_id=uid("u1"))
    )
    # human-owned t2 is excluded — checkout would always reject it (eligibility ⇔ claimability)
    assert [t.id for t in ledger.tasks.list_eligible(limit=10)] == [uid("t1")]


def test_runs_running_lists_live_beats_oldest_first(ledger: Ledger) -> None:
    from datetime import UTC, datetime

    from chorus.ledger._models import Run, RunStatus

    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(Task(id=uid("rr-t1"), intent="a", assignee_employee_id="ada"))
    for n, rid in enumerate((uid("rr-r1"), uid("rr-r2"))):
        ledger.runs.create(
            Run(
                id=rid,
                employee_id="ada",
                task_id=uid("rr-t1"),
                status=RunStatus.RUNNING,
                started_at=datetime(2026, 6, 1, 12, n, tzinfo=UTC),
            )
        )
    assert [run.id for run in ledger.runs.running()] == [uid("rr-r1"), uid("rr-r2")]


def test_cost_events_grouped_spend(ledger: Ledger) -> None:
    from datetime import UTC, datetime

    from chorus.ledger._models import CostEvent

    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.employees.create(Employee(id="bex", name="Bex", role="pm"))
    for n, (eid, model, cents) in enumerate(
        [("ada", "gpt-x", 300), ("ada", "gpt-mini", 50), ("bex", "gpt-x", 100)]
    ):
        ledger.cost_events.record(
            CostEvent(
                id=uid(f"ce-{n}"),
                employee_id=eid,
                provider="dream",
                model=model,
                cost_cents=cents,
                input_tokens=10 * (n + 1),
                output_tokens=5,
                occurred_at=datetime(2026, 6, 1 + n, 12, 0, tzinfo=UTC),
            )
        )

    by_model = {row.key: row for row in ledger.cost_events.grouped("model")}
    assert by_model["gpt-x"].cost_cents == 400
    assert by_model["gpt-mini"].cost_cents == 50
    assert by_model["gpt-x"].events == 2

    by_employee = {row.key: row for row in ledger.cost_events.grouped("employee")}
    assert by_employee["ada"].cost_cents == 350

    by_day = {row.key: row for row in ledger.cost_events.grouped("day")}
    assert by_day["2026-06-01"].cost_cents == 300
    assert len(by_day) == 3

    try:
        ledger.cost_events.grouped("provider; DROP TABLE cost_event")  # type: ignore[arg-type]
        raise AssertionError("unreachable")
    except ValueError:
        pass  # closed whitelist — never interpolate a caller string
