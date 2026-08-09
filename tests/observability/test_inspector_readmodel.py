"""The inspector read-model projections (spec 08 §3, spec 14 F1) — status / task / stuck.

Pure reads over the ledger: names resolved, liveness derived from the canonical
:func:`chorus.lifecycle.classify` (not byte-silence), blockers from the *unresolved* dependency
leaves. The inspector takes an injected clock so liveness (which compares run leases to ``now``) is
deterministic under test.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from chorus.ledger import (
    Activity,
    ActivityVerb,
    Artifact,
    ArtifactRevision,
    ArtifactType,
    CostEvent,
    Goal,
    Ledger,
    Run,
    RunStatus,
    Task,
    TaskStatus,
)
from chorus.observability import LedgerInspector
from chorus.outcomes import Verifier
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration

_NOW = datetime(2026, 6, 16, 12, 0, tzinfo=UTC)


@pytest.fixture
def ledger() -> Iterator[Ledger]:
    lg = open_test_ledger()
    try:
        yield lg
    finally:
        lg.close()


def _inspector(ledger: Ledger) -> LedgerInspector:
    return LedgerInspector(ledger, clock=lambda: _NOW)


def _seed(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="mgr", name="Moe", role="engineer"))
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer", reports_to="mgr"))
    ledger.employees.create(Employee(id="bob", name="Bob", role="engineer", reports_to="mgr"))
    # active: in-progress with a live lease → healthy, and a running beat to count
    ledger.tasks.submit(
        Task(
            id=uid("active"),
            intent="ship it",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
        )
    )
    ledger.runs.create(
        Run(
            id=uid("r_active"),
            employee_id="ada",
            task_id=uid("active"),
            status=RunStatus.RUNNING,
            lease_expires_at=_NOW + timedelta(hours=1),
        )
    )
    # stuck: in-progress with no run/wake/monitor/recovery → stranded_in_progress (STALLED)
    ledger.tasks.submit(
        Task(
            id=uid("stuck"),
            intent="orphaned work",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="bob",
        )
    )
    # done: terminal, excluded from open/blocked
    ledger.tasks.submit(
        Task(id=uid("done"), intent="shipped", status=TaskStatus.DONE, assignee_employee_id="ada")
    )


def test_status_projects_the_company(ledger: Ledger) -> None:
    _seed(ledger)
    status = _inspector(ledger).status()
    assert {e.id for e in status.employees} == {"mgr", "ada", "bob"}
    assert {(e.name, e.role) for e in status.employees if e.id == "ada"} == {("Ada", "engineer")}
    assert status.open_tasks == 2  # active + stuck; done is terminal
    assert status.running_beats == 1  # r_active
    assert {t.id for t in status.blocked} == {uid("stuck")}  # only the stalled one
    assert isinstance(status.open_incidents, tuple)


def test_stuck_lists_only_stalled_non_terminal_tasks(ledger: Ledger) -> None:
    _seed(ledger)
    assert {t.id for t in _inspector(ledger).stuck()} == {uid("stuck")}


def test_task_resolves_name_liveness_and_unresolved_blockers(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(id=uid("blk"), intent="prereq", status=TaskStatus.TODO, assignee_employee_id="ada")
    )
    ledger.tasks.submit(
        Task(
            id=uid("t"),
            intent="the work",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
        )
    )
    ledger.dependencies.add(uid("t"), uid("blk"))
    view = _inspector(ledger).task(uid("t"))
    assert view.id == uid("t")
    assert view.assignee == "Ada"  # name resolved, not the id
    assert view.status is TaskStatus.IN_PROGRESS
    assert view.blockers == (uid("blk"),)  # unresolved leaf
    assert view.liveness == "stalled"  # in-progress, no live run/wake → stranded


def test_task_done_blocker_is_not_a_blocker(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("blk"), intent="prereq", status=TaskStatus.DONE))
    ledger.tasks.submit(Task(id=uid("t"), intent="the work", status=TaskStatus.TODO))
    ledger.dependencies.add(uid("t"), uid("blk"))
    assert _inspector(ledger).task(uid("t")).blockers == ()  # resolved → not surfaced


def test_task_thread_walks_goal_subtree_and_attached_rows(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.goals.create(Goal(id=uid("goal"), title="Ship it"))
    ledger.tasks.submit(
        Task(
            id=uid("parent"),
            intent="parent work",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
            goal_id=uid("goal"),
        )
    )
    ledger.tasks.submit(
        Task(
            id=uid("child"),
            intent="child work",
            status=TaskStatus.TODO,
            assignee_employee_id="ada",
            goal_id=uid("goal"),
            parent_id=uid("parent"),
            depth=1,
        )
    )
    ledger.tasks.submit(
        Task(
            id=uid("sibling"),
            intent="second child",
            status=TaskStatus.BACKLOG,
            assignee_employee_id="ada",
            goal_id=uid("goal"),
            parent_id=uid("parent"),
            depth=1,
        )
    )
    ledger.dod.create(uid("parent"), Verifier.command("pytest -q", artifact_class="report"))
    ledger.dod.create(uid("child"), Verifier.command("ruff check", artifact_class="patch"))
    ledger.runs.create(
        Run(
            id=uid("run_parent"),
            employee_id="ada",
            task_id=uid("parent"),
            status=RunStatus.RUNNING,
            lease_expires_at=_NOW + timedelta(hours=1),
        )
    )
    ledger.runs.create(
        Run(id=uid("run_child"), employee_id="ada", task_id=uid("child"), status=RunStatus.QUEUED)
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("cost_parent"),
            employee_id="ada",
            task_id=uid("parent"),
            run_id=uid("run_parent"),
            provider="openai",
            model="gpt-5",
            cost_cents=11,
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("cost_child"),
            employee_id="ada",
            task_id=uid("child"),
            run_id=uid("run_child"),
            provider="openai",
            model="gpt-5-mini",
            cost_cents=7,
        )
    )
    ledger.artifacts.create(
        Artifact(id=uid("artifact_parent"), task_id=uid("parent"), type=ArtifactType.DOC)
    )
    ledger.artifacts.create(
        Artifact(id=uid("artifact_child"), task_id=uid("child"), type=ArtifactType.DOC)
    )
    ledger.artifact_revisions.record(
        ArtifactRevision(id=uid("rev_parent"), artifact_id=uid("artifact_parent"))
    )
    ledger.activity.append(
        Activity(
            id=uid("task_parent_activity"),
            verb=ActivityVerb.ASSIGNED,
            subject_kind="task",
            subject_id=uid("parent"),
            actor_employee_id="ada",
        )
    )
    ledger.activity.append(
        Activity(
            id=uid("task_child_activity"),
            verb=ActivityVerb.DECOMPOSED,
            subject_kind="task",
            subject_id=uid("child"),
            actor_employee_id="ada",
        )
    )
    ledger.activity.append(
        Activity(
            id=uid("artifact_parent_activity"),
            verb=ActivityVerb.PROMOTED,
            subject_kind="artifact",
            subject_id=uid("artifact_parent"),
            actor_employee_id="ada",
        )
    )
    ledger.activity.append(
        Activity(
            id=uid("artifact_child_activity"),
            verb=ActivityVerb.PROMOTED,
            subject_kind="artifact",
            subject_id=uid("artifact_child"),
            actor_employee_id="ada",
        )
    )

    thread = _inspector(ledger).task_thread(uid("parent"))

    assert thread.goal is not None
    assert thread.goal.id == uid("goal")
    assert [entry.task.id for entry in thread.tasks] == [
        uid("parent"),
        uid("child"),
        uid("sibling"),
    ]
    parent, child, sibling = thread.tasks
    assert parent.dod is not None
    assert parent.dod.task_id == uid("parent")
    assert [run.run.id for run in parent.runs] == [uid("run_parent")]
    assert [event.id for event in parent.runs[0].cost_events] == [uid("cost_parent")]
    assert [activity.id for activity in parent.activity] == [uid("task_parent_activity")]
    assert [artifact.artifact.id for artifact in parent.artifacts] == [uid("artifact_parent")]
    assert [revision.id for revision in parent.artifacts[0].revisions] == [uid("rev_parent")]
    assert [activity.id for activity in parent.artifacts[0].activity] == [
        uid("artifact_parent_activity")
    ]
    assert child.dod is not None
    assert child.dod.task_id == uid("child")
    assert [run.run.id for run in child.runs] == [uid("run_child")]
    assert [event.id for event in child.runs[0].cost_events] == [uid("cost_child")]
    assert [activity.id for activity in child.activity] == [uid("task_child_activity")]
    assert [artifact.artifact.id for artifact in child.artifacts] == [uid("artifact_child")]
    assert child.artifacts[0].revisions == ()
    assert [activity.id for activity in child.artifacts[0].activity] == [
        uid("artifact_child_activity")
    ]
    assert sibling.runs == ()
    assert sibling.artifacts == ()
    assert sibling.activity == ()


def test_task_thread_skips_self_parent_cycles(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("loop"), intent="loop forever", parent_id=uid("loop")))

    thread = _inspector(ledger).task_thread(uid("loop"))

    assert [entry.task.id for entry in thread.tasks] == [uid("loop")]


def test_task_thread_keeps_task_only_costs_and_marks_run_task_mismatches(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(Task(id=uid("parent"), intent="parent work", assignee_employee_id="ada"))
    ledger.tasks.submit(
        Task(id=uid("child"), intent="child work", parent_id=uid("parent"), assignee_employee_id="ada")
    )
    ledger.runs.create(Run(id=uid("run_parent"), employee_id="ada", task_id=uid("parent")))
    ledger.cost_events.record(
        CostEvent(
            id=uid("cost_matched"),
            employee_id="ada",
            task_id=uid("parent"),
            run_id=uid("run_parent"),
            provider="openai",
            model="gpt-5",
            cost_cents=11,
            occurred_at=_NOW,
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("cost_task_only"),
            employee_id="ada",
            task_id=uid("parent"),
            provider="openai",
            model="gpt-5",
            cost_cents=7,
            occurred_at=_NOW + timedelta(seconds=1),
        )
    )
    ledger.cost_events.record(
        CostEvent(
            id=uid("cost_mismatched"),
            employee_id="ada",
            task_id=uid("child"),
            run_id=uid("run_parent"),
            provider="openai",
            model="gpt-5",
            cost_cents=5,
            occurred_at=_NOW + timedelta(seconds=2),
        )
    )

    parent, child = _inspector(ledger).task_thread(uid("parent")).tasks

    assert [event.id for event in parent.runs[0].cost_events] == [uid("cost_matched")]
    assert [event.id for event in parent.runs[0].mismatched_cost_events] == [uid("cost_mismatched")]
    assert [event.id for event in parent.task_only_cost_events] == [uid("cost_task_only")]
    assert child.task_only_cost_events == ()


def test_task_thread_orders_tied_artifacts_by_id(ledger: Ledger) -> None:
    ledger.tasks.submit(Task(id=uid("task"), intent="work"))
    first_id, second_id = uid("artifact_a"), uid("artifact_b")
    ledger.artifacts.create(Artifact(id=second_id, task_id=uid("task"), type=ArtifactType.DOC))
    ledger.artifacts.create(Artifact(id=first_id, task_id=uid("task"), type=ArtifactType.DOC))
    for artifact_id in (first_id, second_id):
        ledger._conn.execute(
            "UPDATE artifact SET created_at = ? WHERE id = ?", (_NOW.isoformat(), artifact_id)
        )
    ledger._conn.commit()

    task = _inspector(ledger).task_thread(uid("task")).tasks[0]

    assert [view.artifact.id for view in task.artifacts] == sorted((first_id, second_id))


def test_task_unknown_raises_keyerror(ledger: Ledger) -> None:
    with pytest.raises(KeyError):
        _inspector(ledger).task(uid("nope"))
