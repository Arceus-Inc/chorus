"""AgentSessionRepo — the handle rows pointing at dream sessions (migration 0005)."""

from __future__ import annotations

import pytest

from chorus.ledger import (
    AgentSession,
    AgentSessionStatus,
    Ledger,
    LedgerIntegrityError,
    Run,
    SessionCost,
    Task,
)
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = pytest.mark.integration


def _employee(ledger: Ledger, eid: str) -> None:
    ledger.employees.create(Employee(id=eid, name=eid, role="engineer"))


def _task(ledger: Ledger, task_id: str, *, assignee: str | None = None) -> str:
    ledger.tasks.submit(
        Task(id=task_id, intent="agent session test", assignee_employee_id=assignee)
    )
    return task_id


def _session(
    ledger: Ledger,
    *,
    session_id: str | None = None,
    dream_key: str | None = None,
    employee_id: str,
    task_id: str,
) -> AgentSession:
    return AgentSession(
        id=session_id or uid("sess"),
        dream_session_key=dream_key or uid("dream"),
        employee_id=employee_id,
        task_id=task_id,
        model="claude-sonnet",
    )


def test_open_get_and_get_open_for_task(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    opened = ledger.agent_sessions.open(session)
    assert opened.id == uid("s1")
    assert opened.status is AgentSessionStatus.OPEN
    got = ledger.agent_sessions.get(uid("s1"))
    assert got is not None
    assert got.dream_session_key == session.dream_session_key
    assert got.employee_id == emp
    assert got.task_id == task_id
    assert ledger.agent_sessions.get_open_for_task(task_id) == got


def test_second_open_for_same_task_raises(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.agent_sessions.open(_session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1")))
    with pytest.raises(LedgerIntegrityError):
        ledger.agent_sessions.open(
            _session(
                ledger,
                employee_id=emp,
                task_id=task_id,
                session_id=uid("s2"),
                dream_key=uid("dream2"),
            )
        )


def test_bind_working_dir_records_where_the_thread_works(ledger: Ledger) -> None:
    """dream refuses to resume into another directory; chorus records the same fact.

    Knowing the directory here lets the control plane see a mismatch coming
    instead of learning about it from a failed resume mid-beat.
    """
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    assert session.working_dir is None

    ledger.agent_sessions.bind_working_dir(session.id, "/srv/worktrees/ada")

    bound = ledger.agent_sessions.get(session.id)
    assert bound is not None
    assert bound.working_dir == "/srv/worktrees/ada"


def test_record_error_sets_and_clears_the_resume_reason(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )

    ledger.agent_sessions.record_error(session.id, "corrupt")
    failed = ledger.agent_sessions.get(session.id)
    assert failed is not None
    assert failed.last_error == "corrupt"

    ledger.agent_sessions.record_error(session.id, None)
    recovered = ledger.agent_sessions.get(session.id)
    assert recovered is not None
    assert recovered.last_error is None


def test_seal_allows_new_open_for_same_task(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    first = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    ledger.agent_sessions.seal(first.id)
    sealed = ledger.agent_sessions.get(first.id)
    assert sealed is not None
    assert sealed.status is AgentSessionStatus.SEALED
    assert ledger.agent_sessions.get_open_for_task(task_id) is None
    second = ledger.agent_sessions.open(
        _session(
            ledger,
            employee_id=emp,
            task_id=task_id,
            session_id=uid("s2"),
            dream_key=uid("dream2"),
        )
    )
    assert second.id == uid("s2")
    assert ledger.agent_sessions.get_open_for_task(task_id) == second


def test_touch_cost_updates_session(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    run_id = uid("run1")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.runs.create(Run(id=run_id, employee_id=emp, task_id=task_id))
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    cost = SessionCost(input_tokens=100, output_tokens=50, cost_usd=0.01)
    ledger.agent_sessions.touch_cost(session.id, cost, run_id=run_id)
    got = ledger.agent_sessions.get(session.id)
    assert got is not None
    assert got.cost.input_tokens == 100
    assert got.cost.output_tokens == 50
    assert got.cost.cost_usd == 0.01
    assert got.run_id == run_id


def test_get_by_dream_key(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    dream_key = uid("dream")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    ledger.agent_sessions.open(
        _session(
            ledger,
            employee_id=emp,
            task_id=task_id,
            session_id=uid("s1"),
            dream_key=dream_key,
        )
    )
    got = ledger.agent_sessions.get_by_dream_key(dream_key)
    assert got is not None
    assert got.id == uid("s1")


def test_abort_session(ledger: Ledger) -> None:
    emp = uid("emp")
    task_id = uid("task")
    _employee(ledger, emp)
    _task(ledger, task_id, assignee=emp)
    session = ledger.agent_sessions.open(
        _session(ledger, employee_id=emp, task_id=task_id, session_id=uid("s1"))
    )
    ledger.agent_sessions.abort(session.id)
    got = ledger.agent_sessions.get(session.id)
    assert got is not None
    assert got.status is AgentSessionStatus.ABORTED
    assert ledger.agent_sessions.get_open_for_task(task_id) is None
