"""CommentTool + ReadCommentsTool — tasks + comments as the coordination channel (OM-3).

Paperclip has no chat: coordination happens as comments on tasks, and an agent's inbox is its
assigned tasks + the comments on them. Chorus's task-anchored ``message`` rows ARE that thread;
these tools are the beat-side verbs. A comment runs nothing — it persists the row and wakes the
recipient (coalesced), exactly like ``deliver_message``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from chorus.heartbeat import BeatContext
from chorus.ledger import Ledger, Task
from chorus.testing import uid
from chorus.workforce import Employee
from chorus_tools import CommentTool, ReadCommentsTool

pytestmark = pytest.mark.integration


def _ctx(working_dir: Path) -> object:
    from dream.tools._context import ToolExecutionContext

    return ToolExecutionContext(
        working_dir=working_dir,
        session_id="sess",
        metadata={},
        scratch_dir=working_dir,
        cancel_requested=False,
    )


def _seed(ledger: Ledger) -> tuple[str, str]:
    """A manager with one report and a parent→child task chain; returns (parent_id, child_id)."""
    ledger.employees.create(Employee(id="mia", name="Mia", role="manager"))
    ledger.employees.create(Employee(id="rex", name="Rex", role="engineer"))
    parent = ledger.tasks.submit(
        Task(id=uid("t-parent"), intent="ship the module", assignee_employee_id="mia")
    )
    child = ledger.tasks.submit(
        Task(
            id=uid("t-child"),
            intent="write the parser",
            parent_id=parent.id,
            assignee_employee_id="rex",
        )
    )
    return parent.id, child.id


def test_a_manager_comment_notifies_the_assignee(ledger: Ledger, tmp_path: Path) -> None:
    parent_id, child_id = _seed(ledger)
    BeatContext(task_id=parent_id, run_id="run1", employee_id="mia").write(tmp_path)

    result = asyncio.run(
        CommentTool(ledger).execute(
            {"task_id": child_id, "body": "parser must handle CRLF"}, _ctx(tmp_path)
        )
    )

    assert result.is_error is False
    thread = ledger.messages.for_task(child_id)
    assert [m.body for m in thread] == ["parser must handle CRLF"]
    assert thread[0].from_employee_id == "mia"
    assert thread[0].to_employee_id == "rex"
    # The run-causing half: the recipient got a coalesced wake, so their next beat sees it.
    assert any(w.employee_id == "rex" for w in ledger.wakes.queued())


def test_an_assignee_comment_escalates_to_the_parent_assignee(
    ledger: Ledger, tmp_path: Path
) -> None:
    _parent_id, child_id = _seed(ledger)
    BeatContext(task_id=child_id, run_id="run2", employee_id="rex").write(tmp_path)

    # No task_id given — the beat task is the default thread.
    result = asyncio.run(
        CommentTool(ledger).execute({"body": "blocked: spec ambiguous"}, _ctx(tmp_path))
    )

    assert result.is_error is False
    thread = ledger.messages.for_task(child_id)
    assert thread[-1].to_employee_id == "mia"  # up the chain, never into the void


def test_read_comments_returns_the_thread(ledger: Ledger, tmp_path: Path) -> None:
    parent_id, child_id = _seed(ledger)
    BeatContext(task_id=parent_id, run_id="run3", employee_id="mia").write(tmp_path)
    asyncio.run(CommentTool(ledger).execute({"task_id": child_id, "body": "one"}, _ctx(tmp_path)))
    asyncio.run(CommentTool(ledger).execute({"task_id": child_id, "body": "two"}, _ctx(tmp_path)))

    result = asyncio.run(ReadCommentsTool(ledger).execute({"task_id": child_id}, _ctx(tmp_path)))

    assert result.is_error is False
    comments = result.structured["comments"]
    assert [c["body"] for c in comments] == ["one", "two"]
    assert comments[0]["author"] == "mia"


def test_comment_on_an_unknown_task_is_refused(ledger: Ledger, tmp_path: Path) -> None:
    parent_id, _ = _seed(ledger)
    BeatContext(task_id=parent_id, run_id="run4", employee_id="mia").write(tmp_path)

    result = asyncio.run(
        CommentTool(ledger).execute({"task_id": uid("t-ghost"), "body": "x"}, _ctx(tmp_path))
    )

    assert result.structured["status"] == "refused"
