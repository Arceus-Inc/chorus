"""Eval: the dream session key survives a ledger reconnect (process restart simulation).

Chorus's half of cross-process continuity is small: after a restart, looking up
the task has to return the *same* handle — same row, same ``dream_session_key``,
same accumulated spend — because that key is the only thing that reopens the
conversation. dream's own eval covers reloading the transcript behind it.
"""

from __future__ import annotations

import uuid

import pytest

from chorus.ledger import Ledger, SessionCost, Task, ensure_open_session
from chorus.testing import uid
from chorus.workforce import Employee

pytestmark = [pytest.mark.integration, pytest.mark.e2e]


def test_eval_agent_session_handle_survives_reconnect(pg_database: str) -> None:
    company_id = str(uuid.uuid4())
    emp = uid("emp")
    task_id = uid("task")
    dream_key = uid("dream")

    store = Ledger.open(pg_database, company_id=company_id)
    store.employees.create(Employee(id=emp, name=emp, role="engineer"))
    store.tasks.submit(Task(id=task_id, intent="resume eval", assignee_employee_id=emp))
    session = ensure_open_session(
        store,
        employee_id=emp,
        task_id=task_id,
        dream_session_key=dream_key,
        model="claude-sonnet",
        run_id=None,
        working_dir="/srv/worktrees/ada",
    )
    session_id = session.id
    store.agent_sessions.touch_cost(
        session_id, SessionCost(input_tokens=120, output_tokens=40, cost_usd=0.02)
    )
    store.close()

    resumed = Ledger.open(pg_database, company_id=company_id)
    try:
        open_session = resumed.agent_sessions.get_open_for_task(task_id)
        assert open_session is not None
        assert open_session.id == session_id
        assert open_session.dream_session_key == dream_key
        assert open_session.working_dir == "/srv/worktrees/ada"
        # Spend is chorus's to carry across the restart — budgets read it.
        assert open_session.cost.input_tokens == 120
        assert open_session.cost.cost_usd == 0.02
        # And the key round-trips by its own index, which is how a control
        # plane goes from a dream session back to the task that owns it.
        assert resumed.agent_sessions.get_by_dream_key(dream_key) == open_session
    finally:
        resumed.close()
