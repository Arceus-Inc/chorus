"""The task-context projector — the packet is a pure function of durable rows.

These are integration tests because the ledger is Postgres-only. The properties they pin are the
reason the packet exists:

- a delegated child can state *why* it is doing the work and *what* done means;
- a second beat on a task can see what the first beat did and what the evaluator said about it;
- projecting twice changes nothing.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chorus.context import project_task_context
from chorus.ledger import Ledger, Run, RunStatus, Task, TaskStatus
from chorus.memory import EpisodicStore, SprintDelta
from chorus.outcomes import Verifier
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)


def _employee(ledger: Ledger, employee_id: str = "e1") -> Employee:
    return ledger.employees.create(
        Employee(id=employee_id, name=employee_id, role="backend_engineer")
    )


def _finished_run(
    ledger: Ledger,
    *,
    task_id: str,
    employee_id: str,
    run_id: str,
    outcome: dict[str, object],
) -> None:
    ledger.runs.create(Run(id=run_id, employee_id=employee_id, task_id=task_id))
    ledger.runs.finish(run_id, RunStatus.SUCCEEDED, outcome=outcome)


async def test_delegated_child_knows_why_and_what(ledger: Ledger) -> None:
    """The two questions an IC beat cannot currently answer: why am I doing this, and what is done."""
    employee = _employee(ledger)
    from chorus.ledger import Goal

    root_goal = ledger.goals.create(Goal(id=uid("g-root"), title="Ship the editor"))
    parent_id = uid("t-parent")
    child_id = uid("t-child")
    ledger.tasks.submit(
        Task(
            id=parent_id, intent="Build the timeline", status=TaskStatus.TODO, goal_id=root_goal.id
        )
    )
    ledger.tasks.submit(
        Task(
            id=child_id,
            intent="Implement scrubbing",
            status=TaskStatus.TODO,
            parent_id=parent_id,
            goal_id=root_goal.id,
            assignee_employee_id=employee.id,
        )
    )
    ledger.dod.create(child_id, Verifier.command("pytest tests/test_scrub.py"))

    packet = project_task_context(ledger, task_id=child_id, run_id=uid("run-1"), employee=employee)

    # why: root goal first, then the task that delegated down to this one.
    assert [(link.kind, link.title) for link in packet.why] == [
        ("goal", "Ship the editor"),
        ("task", "Build the timeline"),
    ]
    # what: the DoD verbatim, not a paraphrase.
    assert packet.what.intent == "Implement scrubbing"
    assert packet.what.dod_kind == "command"
    assert packet.what.dod_spec == "pytest tests/test_scrub.py"
    assert packet.what.artifact_class == "pr"
    assert packet.what.scope_guard
    assert packet.is_first_beat


async def test_second_beat_sees_the_first(ledger: Ledger, tmp_path: Path) -> None:
    """The state-carry regression test: beat 2 can read beat 1's landing and the evaluator's finding."""
    employee = _employee(ledger)
    task_id = uid("t-retry")
    first_run = uid("run-first")
    ledger.tasks.submit(
        Task(
            id=task_id,
            intent="Implement scrubbing",
            status=TaskStatus.TODO,
            assignee_employee_id=employee.id,
        )
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    _finished_run(
        ledger,
        task_id=task_id,
        employee_id=employee.id,
        run_id=first_run,
        outcome={
            "landed": {
                "phase": "needs_rework",
                "recovery_hint": "rework",
                "passed": False,
                "diagnostic": "base62 alphabet order is wrong",
                "summary": "DoD failed — rework",
            }
        },
    )
    # the evaluator's prose, where dream leaves it
    evals = tmp_path / "docs" / "evals" / first_run
    evals.mkdir(parents=True)
    (evals / "sprint-1.json").write_text(
        json.dumps({"notes": "tests assert the wrong vectors"}), encoding="utf-8"
    )
    episodic = EpisodicStore(tmp_path / "memory")
    episodic.append(
        SprintDelta(
            run_id=first_run,
            task_id=task_id,
            employee_id=employee.id,
            scope="project",
            intent="Implement scrubbing",
            outcome="needs_changes",
            score=0.0,
            created_at=_NOW,
            files_touched=("src/scrub.py",),
            body="tried the naive approach",
        )
    )

    packet = project_task_context(
        ledger,
        task_id=task_id,
        run_id=uid("run-second"),
        employee=employee,
        episodic=episodic,
        worktree=tmp_path,
    )

    assert not packet.is_first_beat
    (beat,) = packet.prior_beats
    assert beat.run_id == first_run
    assert beat.beat_number == 1
    assert beat.phase == "needs_rework"
    assert beat.recovery_hint == "rework"
    assert beat.passed is False
    assert beat.outcome == "needs_changes"
    assert beat.files_touched == ("src/scrub.py",)
    assert beat.summary == "tried the naive approach"
    # both verdict sources land, ledger-first
    assert "base62 alphabet order is wrong" in beat.verdict_notes
    assert any("tests assert the wrong vectors" in note for note in beat.verdict_notes)


async def test_projection_is_pure(ledger: Ledger) -> None:
    """Same rows in, identical packet out — the property the snapshot tests rest on."""
    employee = _employee(ledger)
    task_id = uid("t-pure")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee.id)
    )
    ledger.dod.create(task_id, Verifier.command("true"))
    run_id = uid("run-pure")

    first = project_task_context(ledger, task_id=task_id, run_id=run_id, employee=employee)
    second = project_task_context(ledger, task_id=task_id, run_id=run_id, employee=employee)

    assert first == second
    assert first.to_dict() == second.to_dict()


async def test_current_run_is_excluded_and_window_is_bounded(ledger: Ledger) -> None:
    """A beat must not be told about itself, and the projection is bounded before rendering."""
    employee = _employee(ledger)
    task_id = uid("t-window")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee.id)
    )
    run_ids = [uid(f"run-{index}") for index in range(4)]
    for run_id in run_ids:
        _finished_run(
            ledger, task_id=task_id, employee_id=employee.id, run_id=run_id, outcome={"landed": {}}
        )
    current = uid("run-current")
    ledger.runs.create(Run(id=current, employee_id=employee.id, task_id=task_id))

    packet = project_task_context(
        ledger, task_id=task_id, run_id=current, employee=employee, max_prior_beats=2
    )

    assert [beat.run_id for beat in packet.prior_beats] == run_ids[-2:]
    assert current not in {beat.run_id for beat in packet.prior_beats}
    # numbering reflects the true history, not the window
    assert [beat.beat_number for beat in packet.prior_beats] == [3, 4]
    # the unfinished current run still counts toward the budget's beat number
    assert packet.budget.beat_number == 5


async def test_degrades_without_episodic_or_worktree(ledger: Ledger) -> None:
    """A young company has no episodic store and no evals on disk. A thin packet beats no packet."""
    employee = _employee(ledger)
    task_id = uid("t-thin")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee.id)
    )
    _finished_run(
        ledger,
        task_id=task_id,
        employee_id=employee.id,
        run_id=uid("run-thin"),
        outcome={"landed": {"phase": "terminal_pass", "summary": "DoD passed"}},
    )

    packet = project_task_context(ledger, task_id=task_id, run_id=uid("run-now"), employee=employee)

    (beat,) = packet.prior_beats
    assert beat.phase == "terminal_pass"
    assert beat.summary == "DoD passed"  # falls back to the landed summary
    assert beat.files_touched == ()


async def test_unread_messages_are_projected_not_consumed(ledger: Ledger) -> None:
    """The packet reads the inbox; consuming it is a side effect that belongs at the inject site."""
    from chorus.ledger import Message

    employee = _employee(ledger)
    task_id = uid("t-inbox")
    ledger.tasks.submit(
        Task(id=task_id, intent="ship", status=TaskStatus.TODO, assignee_employee_id=employee.id)
    )
    ledger.messages.send(
        Message(id=uid("m1"), to_employee_id=employee.id, body="ping", from_user_id="founder")
    )

    packet = project_task_context(
        ledger, task_id=task_id, run_id=uid("run-inbox"), employee=employee
    )

    (item,) = packet.inbox
    assert item.body == "ping"
    assert item.from_id == "founder"
    assert len(ledger.messages.inbox(employee.id)) == 1  # still unread


async def test_missing_task_raises(ledger: Ledger) -> None:
    """A packet for a task that does not exist is a kernel bug — surface it, do not project empty."""
    employee = _employee(ledger)
    with pytest.raises(KeyError):
        project_task_context(ledger, task_id=uid("t-nope"), run_id=uid("run-x"), employee=employee)
