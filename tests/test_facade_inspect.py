"""The facade read-model tier (spec 14 F1) — flat ``status()`` + the ``org.inspect`` group.

``status()`` is the high-level one-call glance (flat on ``Chorus``); the finer reads live behind
``org.inspect`` (task / stuck / events / scrum_packet / org_report). Both delegate to the same
``LedgerInspector`` the composition root holds.
"""

from __future__ import annotations

import pytest

from chorus.facade import Caps, Chorus
from chorus.ledger import Artifact, ArtifactType, Goal, Ledger, Task, TaskStatus
from chorus.observability import (
    EventBus,
    LedgerInspector,
    TaskThreadView,
    TaskView,
    WorkforceStatus,
)
from chorus.outcomes import Verifier
from chorus.roles import RoleRegistry, default_roles
from chorus.testing import open_test_ledger, uid
from chorus.workforce import Employee, LedgerWorkforce

pytestmark = pytest.mark.integration


def _chorus(ledger: Ledger) -> Chorus:
    return Chorus(
        ledger=ledger,
        workforce=LedgerWorkforce(ledger.employees),
        memory_writer=None,  # type: ignore[arg-type]
        scheduler=None,  # type: ignore[arg-type]
        event_bus=EventBus(),
        inspector=LedgerInspector(ledger),
        dream=None,
        roles=RoleRegistry.from_plugins(default_roles()),
        caps=Caps(),
    )


def _seed(ledger: Ledger) -> None:
    ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
    ledger.tasks.submit(
        Task(
            id=uid("t1"),
            intent="ship it",
            status=TaskStatus.IN_PROGRESS,
            assignee_employee_id="ada",
        )
    )


def test_status_is_flat_and_projects_the_company() -> None:
    ledger = open_test_ledger()
    try:
        _seed(ledger)
        status = _chorus(ledger).status()
        assert isinstance(status, WorkforceStatus)
        assert {e.id for e in status.employees} == {"ada"}
        assert status.open_tasks == 1
    finally:
        ledger.close()


def test_inspect_group_task_resolves_a_view() -> None:
    ledger = open_test_ledger()
    try:
        _seed(ledger)
        view = _chorus(ledger).inspect.task(uid("t1"))
        assert isinstance(view, TaskView)
        assert view.assignee == "Ada"
    finally:
        ledger.close()


def test_inspect_group_task_thread_resolves_a_tree() -> None:
    ledger = open_test_ledger()
    try:
        ledger.employees.create(Employee(id="ada", name="Ada", role="engineer"))
        ledger.goals.create(Goal(id=uid("goal"), title="Ship"))
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
        ledger.dod.create(uid("parent"), Verifier.command("pytest -q", artifact_class="report"))
        ledger.artifacts.create(
            Artifact(id=uid("artifact"), task_id=uid("parent"), type=ArtifactType.DOC)
        )

        view = _chorus(ledger).inspect.task_thread(uid("parent"))

        assert isinstance(view, TaskThreadView)
        assert view.goal is not None
        assert view.goal.id == uid("goal")
        assert [entry.task.id for entry in view.tasks] == [uid("parent"), uid("child")]
        assert view.tasks[0].dod is not None
        assert [artifact.artifact.id for artifact in view.tasks[0].artifacts] == [uid("artifact")]
    finally:
        ledger.close()


def test_inspect_group_stuck_lists_stalled_tasks() -> None:
    ledger = open_test_ledger()
    try:
        _seed(ledger)  # t1 is in-progress with no live run → stalled
        assert [v.id for v in _chorus(ledger).inspect.stuck()] == [uid("t1")]
    finally:
        ledger.close()


def test_inspect_group_events_replays_the_stream() -> None:
    ledger = open_test_ledger()
    try:
        _seed(ledger)
        # no events emitted on this bus → empty replay, but the method is wired (no stub)
        assert list(_chorus(ledger).inspect.events()) == []
    finally:
        ledger.close()


def test_task_unknown_raises_through_the_group() -> None:
    ledger = open_test_ledger()
    try:
        with pytest.raises(KeyError):
            _chorus(ledger).inspect.task(uid("nope"))
    finally:
        ledger.close()
