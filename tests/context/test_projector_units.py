"""Projector unit tests over a fake ledger — no Postgres required.

The projector touches six repo reads and nothing else. That surface is narrow enough to fake, which
is worth stating plainly: if projecting a beat's context needed a live database, the seam would be
in the wrong place. These tests run everywhere and pin the logic; the integration suite in
``test_project_task_context.py`` pins the same behaviour against a real ledger.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from chorus.context import PACKET_VERSION, project_task_context
from chorus.ledger import Goal, Message, Run, RunStatus, Task, TaskStatus
from chorus.outcomes import Verifier
from chorus.workforce import Employee

_NOW = datetime(2026, 6, 17, 12, 0, tzinfo=UTC)
_EMPLOYEE = Employee(id="e1", name="e1", role="backend_engineer")


class _Tasks:
    def __init__(self, tasks: dict[str, Task]) -> None:
        self._tasks = tasks

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)


class _Runs:
    def __init__(self, runs: list[Run]) -> None:
        self._runs = runs

    def for_task(self, task_id: str) -> list[Run]:
        return [run for run in self._runs if run.task_id == task_id]


class _Dod:
    def __init__(self, verifiers: dict[str, Verifier]) -> None:
        self._verifiers = verifiers

    def verifier_for_task(self, task_id: str) -> Verifier | None:
        return self._verifiers.get(task_id)


class _Goals:
    def __init__(self, goals: dict[str, Goal]) -> None:
        self._goals = goals

    def get(self, goal_id: str) -> Goal | None:
        return self._goals.get(goal_id)


class _Messages:
    def __init__(self, messages: list[Message]) -> None:
        self._messages = messages

    def inbox(self, employee_id: str) -> list[Message]:
        return [m for m in self._messages if m.to_employee_id == employee_id]


class _CostEvents:
    def __init__(self, spent: int) -> None:
        self._spent = spent

    def spent_cents(self, employee_id: str, *, since: datetime | None = None) -> int:
        return self._spent


class _FakeLedger:
    """Exactly the six reads the projector performs — nothing more."""

    def __init__(
        self,
        *,
        tasks: dict[str, Task],
        runs: list[Run] | None = None,
        verifiers: dict[str, Verifier] | None = None,
        goals: dict[str, Goal] | None = None,
        messages: list[Message] | None = None,
        spent_cents: int = 0,
    ) -> None:
        self.tasks = _Tasks(tasks)
        self.runs = _Runs(runs or [])
        self.dod = _Dod(verifiers or {})
        self.goals = _Goals(goals or {})
        self.messages = _Messages(messages or [])
        self.cost_events = _CostEvents(spent_cents)


def _run(run_id: str, task_id: str, outcome: dict[str, object], *, finished: bool = True) -> Run:
    return Run(
        id=run_id,
        employee_id="e1",
        task_id=task_id,
        status=RunStatus.SUCCEEDED,
        finished_at=_NOW if finished else None,
        outcome=outcome,
    )


def _project(ledger: object, task_id: str, run_id: str = "run-now", **kwargs: object):
    return project_task_context(
        ledger,  # type: ignore[arg-type]
        task_id=task_id,
        run_id=run_id,
        employee=_EMPLOYEE,
        **kwargs,  # type: ignore[arg-type]
    )


def test_why_chain_is_root_first_across_goals_then_tasks() -> None:
    """Root objective, then the narrowing, then your part — the order work is explained in."""
    goals = {
        "g-root": Goal(id="g-root", title="Ship the editor"),
        "g-leaf": Goal(id="g-leaf", title="Timeline works", parent_id="g-root"),
    }
    tasks = {
        "t-root": Task(id="t-root", intent="Build the app", status=TaskStatus.IN_PROGRESS),
        "t-mid": Task(
            id="t-mid",
            intent="Build the timeline",
            status=TaskStatus.IN_PROGRESS,
            parent_id="t-root",
        ),
        "t-leaf": Task(
            id="t-leaf",
            intent="Implement scrubbing",
            status=TaskStatus.TODO,
            parent_id="t-mid",
            goal_id="g-leaf",
        ),
    }
    packet = _project(_FakeLedger(tasks=tasks, goals=goals), "t-leaf")

    assert [(link.kind, link.title) for link in packet.why] == [
        ("goal", "Ship the editor"),
        ("goal", "Timeline works"),
        ("task", "Build the app"),
        ("task", "Build the timeline"),
    ]


def test_command_dod_projects_the_command_agent_review_projects_the_rubric() -> None:
    """ "Spec" means the literal text of the gate, whichever kind of gate it is."""
    tasks = {
        "t-cmd": Task(id="t-cmd", intent="ship", status=TaskStatus.TODO),
        "t-rev": Task(id="t-rev", intent="write", status=TaskStatus.TODO),
    }
    verifiers = {
        "t-cmd": Verifier.command("pytest -q"),
        "t-rev": Verifier.agent_review(rubric="cite every claim"),
    }
    ledger = _FakeLedger(tasks=tasks, verifiers=verifiers)

    command = _project(ledger, "t-cmd")
    review = _project(ledger, "t-rev")

    assert (command.what.dod_kind, command.what.dod_spec) == ("command", "pytest -q")
    assert (review.what.dod_kind, review.what.dod_spec) == ("agent_review", "cite every claim")
    assert review.what.artifact_class == "spec"


def test_task_without_a_dod_still_projects_its_intent() -> None:
    """No gate is a legitimate state; it must not blank the contract section."""
    tasks = {"t": Task(id="t", intent="explore", status=TaskStatus.TODO)}
    packet = _project(_FakeLedger(tasks=tasks), "t")

    assert packet.what.intent == "explore"
    assert packet.what.dod_kind is None
    assert packet.what.scope_guard


def test_prior_beats_read_the_landed_record() -> None:
    """The typed phase persisted at the choke point is what makes a retry informed."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [
        _run(
            "run-1",
            "t",
            {
                "landed": {
                    "phase": "needs_rework",
                    "recovery_hint": "rework",
                    "passed": False,
                    "diagnostic": "wrong vectors",
                },
                "sprint_outcomes": "1 failed",
            },
        )
    ]
    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t")

    (beat,) = packet.prior_beats
    assert (beat.phase, beat.recovery_hint, beat.passed) == ("needs_rework", "rework", False)
    assert "wrong vectors" in beat.verdict_notes
    assert "sprint_outcomes: 1 failed" in beat.verdict_notes


def test_unfinished_and_current_runs_are_excluded() -> None:
    """A beat is never told about itself, nor about a run still in flight."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [
        _run("run-done", "t", {"landed": {}}),
        _run("run-inflight", "t", {}, finished=False),
        _run("run-now", "t", {}, finished=False),
    ]
    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t", run_id="run-now")

    assert [beat.run_id for beat in packet.prior_beats] == ["run-done"]
    assert packet.budget.beat_number == 3


def test_window_bounds_recent_beats_but_numbering_stays_absolute() -> None:
    """Dropping old beats must not renumber the ones that remain."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [_run(f"run-{i}", "t", {"landed": {}}) for i in range(5)]
    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t", run_id="run-now", max_prior_beats=2)

    assert [beat.run_id for beat in packet.prior_beats] == ["run-3", "run-4"]
    assert [beat.beat_number for beat in packet.prior_beats] == [4, 5]


def test_summary_is_capped_at_projection_time() -> None:
    """Bounding here keeps the packet itself small, rather than carrying KB to drop later."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [_run("run-1", "t", {"landed": {"summary": "x" * 2000}})]
    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t")

    (beat,) = packet.prior_beats
    assert len(beat.summary) <= 600
    assert beat.summary.endswith("…")


def test_evaluator_notes_are_read_from_the_worktree(tmp_path: Path) -> None:
    """dream leaves the evaluator's prose on disk; the packet is what carries it to the next beat."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [_run("run-1", "t", {"landed": {}})]
    evals = tmp_path / "docs" / "evals" / "run-1"
    evals.mkdir(parents=True)
    (evals / "sprint-1.json").write_text(json.dumps({"notes": "missing edge case"}), "utf-8")
    (evals / "sprint-2.json").write_text("not json at all", "utf-8")  # must not raise

    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t", worktree=tmp_path)

    (beat,) = packet.prior_beats
    assert any("missing edge case" in note for note in beat.verdict_notes)


def test_verdict_notes_are_deduplicated_in_order() -> None:
    """The same finding reaching the packet twice should read once."""
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [_run("run-1", "t", {"landed": {"diagnostic": "same"}, "error": "same"})]
    packet = _project(_FakeLedger(tasks=tasks, runs=runs), "t")

    (beat,) = packet.prior_beats
    assert beat.verdict_notes.count("same") == 1


def test_cyclic_parent_chain_terminates() -> None:
    """A corrupt row must not hang a beat."""
    tasks = {
        "a": Task(id="a", intent="a", status=TaskStatus.TODO, parent_id="b"),
        "b": Task(id="b", intent="b", status=TaskStatus.TODO, parent_id="a"),
    }
    packet = _project(_FakeLedger(tasks=tasks), "a")

    assert [link.id for link in packet.why] == ["b"]


def test_inbox_and_budget_are_projected() -> None:
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    messages = [Message(id="m1", to_employee_id="e1", body="ping", from_user_id="founder")]
    ledger = _FakeLedger(tasks=tasks, messages=messages, spent_cents=1234)

    packet = _project(ledger, "t")

    (item,) = packet.inbox
    assert (item.from_id, item.body) == ("founder", "ping")
    assert packet.budget.spent_cents == 1234
    assert packet.budget.limit_cents == _EMPLOYEE.budget_monthly_cents


def test_packet_is_json_serialisable_and_versioned() -> None:
    """The packet is written to the worktree, so it must survive a JSON round-trip unchanged.

    Round-trip *equality* is the point, not merely "it serialises": the file's job is to be a diff
    target against a freshly projected packet.
    """
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    packet = _project(_FakeLedger(tasks=tasks), "t")

    payload = packet.to_dict()
    assert payload["packet_version"] == PACKET_VERSION
    assert json.loads(json.dumps(payload)) == payload


def test_projection_is_pure() -> None:
    tasks = {"t": Task(id="t", intent="ship", status=TaskStatus.TODO)}
    runs = [_run("run-1", "t", {"landed": {"phase": "terminal_pass"}})]
    ledger = _FakeLedger(tasks=tasks, runs=runs)

    assert _project(ledger, "t") == _project(ledger, "t")
